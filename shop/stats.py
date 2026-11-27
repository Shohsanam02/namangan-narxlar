"""Narx va do'kon statistikasi.

Hisoblashlar Python'da qilinadi: ma'lumot hajmi kichik (bir necha do'kon x bir necha o'n mahsulot),
median esa SQLite'da yo'q. Hajm oshsa — kunlik agregat jadvaliga o'tkazish kerak bo'ladi.
"""

from collections import defaultdict
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal
from statistics import median

from django.db.models import Count, F, Q, Sum
from django.utils import timezone

from .models import Discount, Order, OrderItem, PriceEntry, PriceVote, Product, Store

# "Joriy narx" — juftlikning eng so'nggi yozuvidan oldingi shuncha kun ichidagi yozuvlar medianasi.
CURRENT_WINDOW_DAYS = 7
# Bundan eski narxlar "joriy" hisoblanmaydi.
STALE_AFTER_DAYS = 30
# Faollik: oxirgi ACTIVITY_DAYS kun ichidagi buyurtmalar soni.
ACTIVITY_DAYS = 7
ACTIVE_MIN_ORDERS = 5
# 👎 soni 👍 sonidan shuncha ko'p bo'lsa, yozuv hisobdan chiqariladi.
HIDE_SCORE = 3


def hidden_entry_ids():
    return (
        PriceVote.objects.values("entry")
        .annotate(score=Count("id", filter=Q(is_correct=False)) - Count("id", filter=Q(is_correct=True)))
        .filter(score__gte=HIDE_SCORE)
        .values_list("entry", flat=True)
    )


def visible_prices():
    """Statistikada qatnashadigan narx yozuvlari."""
    return PriceEntry.objects.exclude(id__in=hidden_entry_ids())


def _median(values):
    return Decimal(median(values)).quantize(Decimal("1"))


def current_prices(as_of=None):
    """{(store_id, product_id): Decimal} — har bir do'kon/mahsulot juftligi uchun joriy narx.

    Nega median, o'rtacha emas: narxni oddiy foydalanuvchilar yozadi. Bitta odam xato qilib
    "5 000" o'rniga "500 000" yozsa, o'rtacha qiymat buziladi, median esa deyarli o'zgarmaydi.
    """
    today = as_of or timezone.localdate()
    rows = visible_prices().filter(
        date__gt=today - timedelta(days=STALE_AFTER_DAYS), date__lte=today
    ).values_list("store_id", "product_id", "date", "price")

    by_pair = defaultdict(list)
    for store_id, product_id, date, price in rows:
        by_pair[(store_id, product_id)].append((date, price))

    result = {}
    for pair, items in by_pair.items():
        latest = max(d for d, _ in items)
        window_start = latest - timedelta(days=CURRENT_WINDOW_DAYS)
        result[pair] = _median([p for d, p in items if d > window_start])
    return result


def apply_discount(price, percent):
    return (price * (100 - percent) / 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def active_discounts(day=None):
    """{(store_id, product_id): Discount} - shu kuni amalda. Ustma-ust tushsa, kattasi olinadi."""
    day = day or timezone.localdate()
    result = {}
    for d in Discount.objects.filter(start_date__lte=day, end_date__gte=day).order_by("percent"):
        result[(d.store_id, d.product_id)] = d
    return result


def effective_prices():
    """Xaridor to'laydigan narx: {pair: {"price", "base", "discount"}}.

    Sayt, savat va buyurtma shu funksiyadan foydalanadi - hamma joyda bir xil narx chiqishi uchun.
    """
    discounts = active_discounts()
    result = {}
    for pair, base in current_prices().items():
        d = discounts.get(pair)
        price = apply_discount(base, d.percent) if d else base
        result[pair] = {"price": price, "base": base, "discount": d}
    return result


def discount_rows(store=None):
    """Amaldagi va kutilayotgan chegirmalar. Tugaganlari ko'rsatilmaydi."""
    today = timezone.localdate()
    qs = Discount.objects.filter(end_date__gte=today).select_related("store", "product")
    if store:
        qs = qs.filter(store=store)
    prices = current_prices()
    active, upcoming = [], []
    for d in qs:
        base = prices.get((d.store_id, d.product_id))
        row = {"discount": d, "base": base, "price": apply_discount(base, d.percent) if base else None}
        if d.start_date <= today:
            row["days_left"] = (d.end_date - today).days
            active.append(row)
        else:
            row["starts_in"] = (d.start_date - today).days
            upcoming.append(row)
    active.sort(key=lambda r: (r["days_left"], r["discount"].store.name))
    upcoming.sort(key=lambda r: (r["starts_in"], r["discount"].store.name))
    return active, upcoming


def sidebar_stores():
    """Chap panel uchun: do'konlar, mahsulotlar soni va amaldagi chegirmalar soni."""
    prices = current_prices()
    product_count = defaultdict(int)
    for store_id, _ in prices:
        product_count[store_id] += 1
    discount_count = defaultdict(int)
    for pair in active_discounts():
        if pair in prices:
            discount_count[pair[0]] += 1
    return [
        {"store": s, "products": product_count[s.id], "discounts": discount_count[s.id]}
        for s in Store.objects.all()
    ]


def product_offers(product, prices=None):
    """Mahsulot qaysi do'konda qancha — arzonidan qimmatiga. Haftalik o'zgarish foizi bilan."""
    prices = prices if prices is not None else current_prices()
    week_ago = current_prices(timezone.localdate() - timedelta(days=7))
    stores = {s.id: s for s in Store.objects.all()}
    discounts = active_discounts()

    offers = []
    for (store_id, product_id), price in prices.items():
        if product_id != product.id:
            continue
        old = week_ago.get((store_id, product_id))
        change = None
        if old:
            change = float((price - old) / old * 100)
        d = discounts.get((store_id, product_id))
        final = apply_discount(price, d.percent) if d else price
        offers.append({"store": stores[store_id], "price": final, "base": price, "discount": d, "change": change})
    offers.sort(key=lambda o: o["price"])
    return offers


def price_history(product, days=30):
    """Chart.js uchun: har bir do'kon bo'yicha kunlik median narx."""
    today = timezone.localdate()
    start = today - timedelta(days=days - 1)
    labels = [start + timedelta(days=i) for i in range(days)]

    grouped = defaultdict(lambda: defaultdict(list))
    rows = visible_prices().filter(product=product, date__gte=start).values_list("store__name", "date", "price")
    for store_name, date, price in rows:
        grouped[store_name][date].append(price)

    datasets = []
    for store_name in sorted(grouped):
        by_day = grouped[store_name]
        data = [float(_median(by_day[d])) if by_day.get(d) else None for d in labels]
        datasets.append({"label": store_name, "data": data})
    return {"labels": [d.strftime("%d.%m") for d in labels], "datasets": datasets}


def store_activity(stores):
    """{store_id: {...}} — oxirgi ACTIVITY_DAYS kundagi savdo va holat (Faol / Sust / Faolsiz)."""
    since = timezone.now() - timedelta(days=ACTIVITY_DAYS)
    orders = (
        Order.objects.filter(created_at__gte=since)
        .exclude(status="cancelled")
        .values("store_id")
        .annotate(n=Count("id"))
    )
    order_count = {r["store_id"]: r["n"] for r in orders}

    revenue = (
        OrderItem.objects.filter(order__created_at__gte=since)
        .exclude(order__status="cancelled")
        .values("order__store_id")
        .annotate(total=Sum(F("unit_price") * F("quantity")))
    )
    revenue_by_store = {r["order__store_id"]: r["total"] or 0 for r in revenue}

    price_updates = (
        PriceEntry.objects.filter(date__gte=timezone.localdate() - timedelta(days=ACTIVITY_DAYS))
        .values("store_id")
        .annotate(n=Count("id"))
    )
    updates = {r["store_id"]: r["n"] for r in price_updates}

    result = {}
    for s in stores:
        n = order_count.get(s.id, 0)
        if not s.is_open or n == 0:
            status, css = "Faolsiz", "inactive"
        elif n >= ACTIVE_MIN_ORDERS:
            status, css = "Faol", "active"
        else:
            status, css = "Sust", "slow"
        result[s.id] = {
            "orders": n,
            "revenue": revenue_by_store.get(s.id, 0),
            "price_updates": updates.get(s.id, 0),
            "status": status,
            "css": css,
        }
    return result


def store_ranking():
    """Do'konlar reytingi: eng qimmat tepada, eng arzon pastda.

    Narx indeksi = do'kondagi har bir mahsulot narxining shu mahsulotning barcha do'konlardagi
    medianasiga nisbati, o'rtachasi x 100. 100 — o'rtacha, 110 — 10% qimmat, 90 — 10% arzon.

    Nega oddiy o'rtacha narx emas: do'konlar turli mahsulot to'plamini sotadi. Faqat go'sht
    sotadigan do'konning o'rtacha narxi baland chiqadi, garchi go'shti arzon bo'lsa ham.
    Nisbat esa har bir mahsulotni "o'z tarozisida" solishtiradi.
    """
    prices = current_prices()
    stores = list(Store.objects.all())

    by_product = defaultdict(dict)
    for (store_id, product_id), price in prices.items():
        by_product[product_id][store_id] = price

    ratios = defaultdict(list)
    cheapest_count = defaultdict(int)
    for product_id, store_prices in by_product.items():
        if len(store_prices) < 2:  # solishtiradigan boshqa do'kon yo'q
            continue
        med = _median(list(store_prices.values()))
        for store_id, price in store_prices.items():
            ratios[store_id].append(price / med)
        cheapest_count[min(store_prices, key=store_prices.get)] += 1

    activity = store_activity(stores)
    rows = []
    for s in stores:
        r = ratios.get(s.id)
        index = round(float(sum(r) / len(r)) * 100, 1) if r else None
        rows.append(
            {
                "store": s,
                "index": index,
                "products": len(r or []),
                "cheapest": cheapest_count.get(s.id, 0),
                "activity": activity[s.id],
            }
        )
    # Indeksi yo'q do'konlar (solishtirib bo'lmaydi) eng pastda.
    rows.sort(key=lambda x: (x["index"] is None, -(x["index"] or 0)))
    return rows


def cheapest_by_product():
    """Bosh sahifa uchun: har bir mahsulot, eng arzon do'kon va narxlar oralig'i."""
    stores = {s.id: s for s in Store.objects.all()}
    by_product = defaultdict(list)
    for (store_id, product_id), info in effective_prices().items():
        by_product[product_id].append((info["price"], stores[store_id], info["discount"]))

    rows = []
    for p in Product.objects.select_related("category"):
        offers = sorted(by_product.get(p.id, []), key=lambda x: x[0])
        if not offers:
            continue
        rows.append(
            {
                "product": p,
                "min_price": offers[0][0],
                "min_store": offers[0][1],
                "min_discount": offers[0][2],
                "max_price": offers[-1][0],
                "store_count": len(offers),
            }
        )
    return rows


def weekly_report(limit=5):
    """Bu hafta eng ko'p qimmatlashgan va arzonlashgan mahsulotlar (chegirmasiz narx bo'yicha).

    Faqat ikkala haftada ham narxi bor do'kon+mahsulot juftliklari solishtiriladi: aks holda
    ro'yxatga qimmat do'kon qo'shilishining o'zi "narx oshdi" bo'lib ko'rinardi.
    """
    today = timezone.localdate()
    now, before = current_prices(today), current_prices(today - timedelta(days=7))
    pairs = defaultdict(list)
    for pair in now.keys() & before.keys():
        pairs[pair[1]].append((before[pair], now[pair]))

    products = {p.id: p for p in Product.objects.all()}
    rows = []
    for product_id, values in pairs.items():
        old = _median([v[0] for v in values])
        new = _median([v[1] for v in values])
        change = round(float((new - old) / old * 100), 1)
        rows.append({"product": products[product_id], "old": old, "new": new, "change": change})
    up = sorted((r for r in rows if r["change"] > 0), key=lambda r: -r["change"])[:limit]
    down = sorted((r for r in rows if r["change"] < 0), key=lambda r: r["change"])[:limit]
    return up, down


def cheapest_offer_by_product():
    """{product_id: (narx, store_id)} — hozir eng arzon (chegirma bilan)."""
    best = {}
    for (store_id, product_id), info in effective_prices().items():
        if product_id not in best or info["price"] < best[product_id][0]:
            best[product_id] = (info["price"], store_id)
    return best


def alert_rows(user):
    alerts = list(user.price_alerts.select_related("product"))
    if not alerts:
        return []
    best = cheapest_offer_by_product()
    stores = {s.id: s for s in Store.objects.all()}
    rows = []
    for a in alerts:
        offer = best.get(a.product_id)
        rows.append(
            {
                "alert": a,
                "price": offer[0] if offer else None,
                "store": stores[offer[1]] if offer else None,
                "triggered": bool(offer) and offer[0] <= a.target_price,
            }
        )
    rows.sort(key=lambda r: (not r["triggered"], r["alert"].product.name))
    return rows
