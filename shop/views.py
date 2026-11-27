from collections import defaultdict

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from . import images, stats
from .cart import Cart, parse_qty
from .forms import CheckoutForm, PriceAlertForm, PriceEntryForm, SignUpForm
from .models import (
    Category, Favorite, Order, OrderItem, PriceAlert, PriceEntry, PriceVote, Product, Store,
)


def _redirect_next(request, fallback, *args):
    """POST'dagi "next" faqat shu saytning ichki manzili bo'lsa ishlatiladi (open redirect'dan himoya)."""
    url = request.POST.get("next", "")
    if url and url_has_allowed_host_and_scheme(url, {request.get_host()}, require_https=request.is_secure()):
        return redirect(url)
    return redirect(fallback, *args)


def _favorite_ids(user):
    if not user.is_authenticated:
        return set()
    return set(user.favorites.values_list("product_id", flat=True))


def _filter_rows(request, rows):
    """Kategoriya va qidiruv filtri (bosh sahifa va do'kon sahifasi uchun umumiy)."""
    category = request.GET.get("kategoriya", "")
    q = request.GET.get("q", "").strip()
    if category:
        rows = [r for r in rows if r["product"].category.slug == category]
    if q:
        rows = [r for r in rows if q.lower() in r["product"].name.lower()]
    return rows, {"categories": Category.objects.all(), "active_category": category, "q": q}


def home(request):
    rows, filters = _filter_rows(request, stats.cheapest_by_product())
    return render(request, "shop/home.html", {"rows": rows, "sidebar": stats.sidebar_stores(), "favorite_ids": _favorite_ids(request.user), **filters})


def nearby(request):
    """Masofa brauzerda hisoblanadi: foydalanuvchi joylashuvi serverga yuborilmaydi."""
    rows = stats.sidebar_stores()
    return render(
        request,
        "shop/nearby.html",
        {
            "located": [r for r in rows if r["store"].latitude is not None],
            "unlocated": [r for r in rows if r["store"].latitude is None],
        },
    )


def discounts(request):
    active, upcoming = stats.discount_rows()
    return render(
        request,
        "shop/discounts.html",
        {"active": active, "upcoming": upcoming, "sidebar": stats.sidebar_stores()},
    )


def product_detail(request, slug):
    product = get_object_or_404(Product, slug=slug)
    offers = stats.product_offers(product)
    history = stats.price_history(product)
    recent = list(
        PriceEntry.objects.filter(product=product)
        .select_related("store", "author")
        .annotate(
            likes=Count("votes", filter=Q(votes__is_correct=True)),
            dislikes=Count("votes", filter=Q(votes__is_correct=False)),
        )
        .order_by("-date", "-created_at")[:15]
    )
    my_votes, alert = {}, None
    if request.user.is_authenticated:
        my_votes = dict(
            PriceVote.objects.filter(user=request.user, entry__in=recent).values_list("entry_id", "is_correct")
        )
        alert = PriceAlert.objects.filter(user=request.user, product=product).first()
    for e in recent:
        e.my_vote = my_votes.get(e.id)
        e.is_hidden = e.dislikes - e.likes >= stats.HIDE_SCORE
    return render(
        request,
        "shop/product_detail.html",
        {
            "product": product, "offers": offers, "history": history, "recent": recent, "alert": alert,
            "is_favorite": product.id in _favorite_ids(request.user),
        },
    )


def store_detail(request, slug):
    store = get_object_or_404(Store, slug=slug)
    products = {p.id: p for p in Product.objects.select_related("category")}
    items = sorted(
        (
            {"product": products[pid], **info}
            for (sid, pid), info in stats.effective_prices().items()
            if sid == store.id
        ),
        key=lambda x: (x["product"].category.name, x["product"].name),
    )
    items, filters = _filter_rows(request, items)
    active, upcoming = stats.discount_rows(store)
    # Kutilayotgan chegirma mahsulot qatorida ham ko'rinadi (eng yaqini).
    next_by_product = {}
    for r in upcoming:
        next_by_product.setdefault(r["discount"].product_id, r["discount"])
    for item in items:
        item["next_discount"] = next_by_product.get(item["product"].id)
    ranking = {r["store"].id: (i + 1, r) for i, r in enumerate(stats.store_ranking())}
    place, info = ranking[store.id]
    return render(
        request,
        "shop/store_detail.html",
        {
            "store": store, "items": items, "place": place, "info": info, "total_stores": len(ranking),
            "active": active, "upcoming": upcoming, "sidebar": stats.sidebar_stores(),
            "favorite_ids": _favorite_ids(request.user), **filters,
        },
    )


def statistics(request):
    rows = stats.store_ranking()
    chart = {
        "labels": [r["store"].name for r in rows if r["index"] is not None],
        "data": [r["index"] for r in rows if r["index"] is not None],
    }
    return render(
        request,
        "shop/statistics.html",
        {
            "rows": rows,
            "chart": chart,
            "activity_days": stats.ACTIVITY_DAYS,
            "active_min": stats.ACTIVE_MIN_ORDERS,
        },
    )


@login_required
def add_price(request):
    initial = {k: request.GET[k] for k in ("store", "product") if k in request.GET}
    form = PriceEntryForm(request.POST or None, request.FILES or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        # Shu kun uchun allaqachon yozgan bo'lsa — yangi qator emas, eskisini yangilaymiz.
        photo = images.clean_photo(d["photo"]) if d.get("photo") else None
        key = {"author": request.user, "store": d["store"], "product": d["product"], "date": d["date"]}
        with transaction.atomic():
            entry = PriceEntry.objects.select_for_update().filter(**key).first()
            created = entry is None
            if created:
                entry = PriceEntry(**key)
            elif entry.price != d["price"]:
                # Narx o'zgardi: eski ovozlar va rasm eski narxga tegishli edi.
                entry.votes.all().delete()
                entry.photo = ""
            entry.price = d["price"]
            if photo:
                entry.photo = photo
            entry.save()
        messages.success(request, "Narx qo'shildi. Rahmat!" if created else "Bu kungi narxingiz yangilandi.")
        return redirect("product_detail", slug=d["product"].slug)
    return render(request, "shop/add_price.html", {"form": form})


@require_POST
def cart_add(request):
    store = get_object_or_404(Store, pk=request.POST.get("store"))
    product = get_object_or_404(Product, pk=request.POST.get("product"))
    qty = parse_qty(request.POST.get("qty", "1"))
    if qty is None:
        messages.error(request, "Miqdor noto'g'ri.")
    elif not store.is_open:
        messages.error(request, f"{store} hozir buyurtma qabul qilmayapti.")
    elif (store.id, product.id) not in stats.current_prices():
        messages.error(request, "Bu do'konda mahsulotning joriy narxi yo'q.")
    else:
        Cart(request).add(store.id, product.id, qty)
        messages.success(request, f"{product} ({store}) savatga qo'shildi.")
    return _redirect_next(request, "cart")


@require_POST
def cart_change(request):
    delta = {"plus": 1, "minus": -1}.get(request.POST.get("action"))
    if delta:
        Cart(request).change(request.POST.get("store"), request.POST.get("product"), delta)
    return redirect("cart")


@require_POST
def cart_remove(request):
    Cart(request).remove(int(request.POST["store"]), int(request.POST["product"]))
    return redirect("cart")


def _cart_groups(request):
    """Savatni do'konlar bo'yicha guruhlaydi: har bir do'kon — alohida buyurtma."""
    prices = {pair: info["price"] for pair, info in stats.effective_prices().items()}
    stores = {s.id: s for s in Store.objects.all()}
    products = {p.id: p for p in Product.objects.all()}
    groups = defaultdict(lambda: {"items": [], "total": 0})
    for store_id, product_id, qty in Cart(request).items():
        if store_id not in stores or product_id not in products:
            continue
        price = prices.get((store_id, product_id))
        g = groups[store_id]
        g["store"] = stores[store_id]
        subtotal = price * qty if price else None
        g["items"].append({"product": products[product_id], "qty": qty, "price": price, "subtotal": subtotal})
        if subtotal:
            g["total"] += subtotal
    return dict(groups)


def cart_view(request):
    return render(request, "shop/cart.html", {"groups": _cart_groups(request).values()})


@login_required
def checkout(request, store_id):
    group = _cart_groups(request).get(store_id)
    if not group:
        messages.error(request, "Bu do'kon uchun savat bo'sh.")
        return redirect("cart")
    store = group["store"]
    form = CheckoutForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        if not store.is_open:
            messages.error(request, f"{store} hozir buyurtma qabul qilmayapti.")
            return redirect("cart")
        # Buyurtma va uning qatorlari bitta tranzaksiyada: yarim saqlangan buyurtma qolmasligi uchun.
        with transaction.atomic():
            order = form.save(commit=False)
            order.user = request.user
            order.store = store
            order.save()
            OrderItem.objects.bulk_create(
                OrderItem(order=order, product=i["product"], unit_price=i["price"], quantity=i["qty"])
                for i in group["items"]
                if i["price"]
            )
        Cart(request).clear_store(store.id)
        messages.success(request, f"Buyurtma #{order.pk} qabul qilindi. {store} siz bilan bog'lanadi.")
        return redirect("my_orders")
    return render(request, "shop/checkout.html", {"form": form, "group": group})


@login_required
def my_orders(request):
    orders = request.user.orders.select_related("store").prefetch_related("items__product")
    return render(request, "shop/my_orders.html", {"orders": orders})


def signup(request):
    form = SignUpForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        return redirect("home")
    return render(request, "registration/signup.html", {"form": form})


@login_required
@require_POST
def vote_price(request, entry_id):
    entry = get_object_or_404(PriceEntry, pk=entry_id)
    value = {"yes": True, "no": False}.get(request.POST.get("vote"))
    if value is None:
        messages.error(request, "Noto'g'ri ovoz.")
    elif entry.author_id == request.user.id:
        messages.error(request, "O'zingiz yozgan narxga ovoz bera olmaysiz.")
    else:
        mine = PriceVote.objects.filter(user=request.user, entry=entry).first()
        if mine and mine.is_correct == value:
            mine.delete()  # shu tugma qayta bosildi — ovoz qaytarib olinadi
        else:
            PriceVote.objects.update_or_create(user=request.user, entry=entry, defaults={"is_correct": value})
    return _redirect_next(request, "product_detail", entry.product.slug)


@login_required
@require_POST
def toggle_favorite(request, product_id):
    product = get_object_or_404(Product, pk=product_id)
    favorite, created = Favorite.objects.get_or_create(user=request.user, product=product)
    if not created:
        favorite.delete()
    return _redirect_next(request, "favorites")


@login_required
def favorites(request):
    ids = _favorite_ids(request.user)
    rows = [r for r in stats.cheapest_by_product() if r["product"].id in ids]
    priced = {r["product"].id for r in rows}
    return render(
        request,
        "shop/favorites.html",
        {"rows": rows, "without_price": Product.objects.filter(id__in=ids - priced), "favorite_ids": ids},
    )


@login_required
@require_POST
def set_alert(request, product_id):
    product = get_object_or_404(Product, pk=product_id)
    form = PriceAlertForm(request.POST)
    if form.is_valid():
        PriceAlert.objects.update_or_create(
            user=request.user, product=product, defaults={"target_price": form.cleaned_data["target_price"]}
        )
        messages.success(request, f"{product}: narx tushganda «Xabarlar» sahifasida ko'rasiz.")
    else:
        messages.error(request, "Narxni musbat butun son bilan yozing.")
    return redirect("product_detail", slug=product.slug)


@login_required
@require_POST
def delete_alert(request, alert_id):
    get_object_or_404(PriceAlert, pk=alert_id, user=request.user).delete()
    return _redirect_next(request, "alerts")


@login_required
def alerts(request):
    return render(request, "shop/alerts.html", {"rows": stats.alert_rows(request.user)})


@login_required
@require_POST
def reorder(request, order_id):
    """Eski buyurtmadagi mahsulotlarni savatga qaytaradi (bugungi narx bilan)."""
    order = get_object_or_404(Order, pk=order_id, user=request.user)
    if not order.store.is_open:
        messages.error(request, f"{order.store} hozir buyurtma qabul qilmayapti.")
        return redirect("my_orders")
    prices = stats.current_prices()
    cart, skipped, added = Cart(request), [], 0
    for item in order.items.select_related("product"):
        if (order.store_id, item.product_id) in prices:
            # set, add emas: tugma ikki marta bosilsa miqdor ikki baravar bo'lib ketmasin.
            cart.set(order.store_id, item.product_id, item.quantity)
            added += 1
        else:
            skipped.append(item.product.name)
    if added:
        messages.success(request, f"{added} ta mahsulot savatga qo'shildi. Narxlar bugungi.")
    if skipped:
        messages.error(request, "Hozir narxi yo'q, qo'shilmadi: " + ", ".join(skipped))
    return redirect("cart" if added else "my_orders")


def weekly(request):
    up, down = stats.weekly_report()
    return render(request, "shop/weekly.html", {"up": up, "down": down})
