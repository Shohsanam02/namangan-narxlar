from collections import defaultdict

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from . import stats
from .cart import Cart, parse_qty
from .forms import CheckoutForm, PriceEntryForm, SignUpForm
from .models import Category, Order, OrderItem, PriceEntry, Product, Store


def home(request):
    rows = stats.cheapest_by_product()
    category = request.GET.get("kategoriya")
    q = request.GET.get("q", "").strip()
    if category:
        rows = [r for r in rows if r["product"].category.slug == category]
    if q:
        rows = [r for r in rows if q.lower() in r["product"].name.lower()]
    return render(
        request,
        "shop/home.html",
        {"rows": rows, "categories": Category.objects.all(), "active_category": category, "q": q},
    )


def product_detail(request, slug):
    product = get_object_or_404(Product, slug=slug)
    offers = stats.product_offers(product)
    history = stats.price_history(product)
    recent = PriceEntry.objects.filter(product=product).select_related("store", "author")[:15]
    return render(
        request,
        "shop/product_detail.html",
        {"product": product, "offers": offers, "history": history, "recent": recent},
    )


def store_detail(request, slug):
    store = get_object_or_404(Store, slug=slug)
    prices = stats.current_prices()
    products = {p.id: p for p in Product.objects.select_related("category")}
    items = sorted(
        ({"product": products[pid], "price": price} for (sid, pid), price in prices.items() if sid == store.id),
        key=lambda x: (x["product"].category.name, x["product"].name),
    )
    ranking = {r["store"].id: (i + 1, r) for i, r in enumerate(stats.store_ranking())}
    place, info = ranking[store.id]
    return render(
        request,
        "shop/store_detail.html",
        {"store": store, "items": items, "place": place, "info": info, "total_stores": len(ranking)},
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
    form = PriceEntryForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        # Shu kun uchun allaqachon yozgan bo'lsa — yangi qator emas, eskisini yangilaymiz.
        _, created = PriceEntry.objects.update_or_create(
            author=request.user, store=d["store"], product=d["product"], date=d["date"],
            defaults={"price": d["price"]},
        )
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
    return redirect(request.POST.get("next") or "cart")


@require_POST
def cart_remove(request):
    Cart(request).remove(int(request.POST["store"]), int(request.POST["product"]))
    return redirect("cart")


def _cart_groups(request):
    """Savatni do'konlar bo'yicha guruhlaydi: har bir do'kon — alohida buyurtma."""
    prices = stats.current_prices()
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
