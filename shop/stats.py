"""Narx va do'kon statistikasi.

Hisoblashlar Python'da qilinadi: ma'lumot hajmi kichik (bir necha do'kon x bir necha o'n mahsulot),
median esa SQLite'da yo'q. Hajm oshsa — kunlik agregat jadvaliga o'tkazish kerak bo'ladi.
"""

from collections import defaultdict
from datetime import timedelta
from decimal import Decimal
from statistics import median

from django.db.models import Count, F, Sum
from django.utils import timezone

from .models import Order, OrderItem, PriceEntry, Product, Store

# "Joriy narx" — juftlikning eng so'nggi yozuvidan oldingi shuncha kun ichidagi yozuvlar medianasi.
CURRENT_WINDOW_DAYS = 7
# Bundan eski narxlar "joriy" hisoblanmaydi.
STALE_AFTER_DAYS = 30
# Faollik: oxirgi ACTIVITY_DAYS kun ichidagi buyurtmalar soni.
ACTIVITY_DAYS = 7
ACTIVE_MIN_ORDERS = 5


def _median(values):
    return Decimal(median(values)).quantize(Decimal("1"))


def current_prices(as_of=None):
    """{(store_id, product_id): Decimal} — har bir do'kon/mahsulot juftligi uchun joriy narx.

    Nega median, o'rtacha emas: narxni oddiy foydalanuvchilar yozadi. Bitta odam xato qilib
    "5 000" o'rniga "500 000" yozsa, o'rtacha qiymat buziladi, median esa deyarli o'zgarmaydi.
    """
    today = as_of or timezone.localdate()
    rows = PriceEntry.objects.filter(
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


def product_offers(product, prices=None):
    """Mahsulot qaysi do'konda qancha — arzonidan qimmatiga. Haftalik o'zgarish foizi bilan."""
    prices = prices if prices is not None else current_prices()
    week_ago = current_prices(timezone.localdate() - timedelta(days=7))
    stores = {s.id: s for s in Store.objects.all()}

    offers = []
    for (store_id, product_id), price in prices.items():
        if product_id != product.id:
            continue
        old = week_ago.get((store_id, product_id))
        change = None
        if old:
            change = float((price - old) / old * 100)
        offers.append({"store": stores[store_id], "price": price, "change": change})
    offers.sort(key=lambda o: o["price"])
    return offers


def price_history(product, days=30):
    """Chart.js uchun: har bir do'kon bo'yicha kunlik median narx."""
    today = timezone.localdate()
    start = today - timedelta(days=days - 1)
    labels = [start + timedelta(days=i) for i in range(days)]

    grouped = defaultdict(lambda: defaultdict(list))
    rows = PriceEntry.objects.filter(product=product, date__gte=start).values_list("store__name", "date", "price")
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
    prices = current_prices()
    stores = {s.id: s for s in Store.objects.all()}
    by_product = defaultdict(list)
    for (store_id, product_id), price in prices.items():
        by_product[product_id].append((price, stores[store_id]))

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
                "max_price": offers[-1][0],
                "store_count": len(offers),
            }
        )
    return rows
