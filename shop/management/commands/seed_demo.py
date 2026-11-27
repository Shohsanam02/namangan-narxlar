"""Demo ma'lumot: Namangan do'konlari, mahsulotlar, 45 kunlik narx tarixi va buyurtmalar.

DIQQAT: narxlar tasodifiy (taxminiy) — haqiqiy do'kon narxlari emas.
Ishga tushirish:  python manage.py seed_demo  (qayta ishlatsa — eski demo o'chiriladi)
"""
import random
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from shop.models import Category, Discount, Order, OrderItem, PriceEntry, Product, Store

# (nomi, narx koeffitsienti, oxirgi 7 kundagi buyurtmalar soni)
STORES = [
    ("Korzinka", 1.08, 6),
    ("Makro", 1.03, 2),
    ("Havas", 0.94, 9),
    ("Baraka Market", 0.97, 0),
    ("Best Market", 1.00, 3),
]

PRODUCTS = {
    "Go'sht": [("Mol go'shti", "kg", 105000), ("Qo'y go'shti", "kg", 115000), ("Tovuq go'shti", "kg", 38000)],
    "Sabzavot": [
        ("Kartoshka", "kg", 6000), ("Piyoz", "kg", 4500), ("Sabzi", "kg", 4000),
        ("Pomidor", "kg", 14000), ("Bodring", "kg", 12000), ("Karam", "kg", 5000),
    ],
    "Meva": [("Olma", "kg", 15000), ("Banan", "kg", 22000), ("Uzum", "kg", 20000), ("Anor", "kg", 25000)],
    "Oziq-ovqat": [("Sut", "litr", 13000), ("Tuxum", "dona", 1500), ("Un", "kg", 7000)],
}

DAYS = 45


def round100(x):
    return Decimal(int(round(x / 100.0)) * 100)


class Command(BaseCommand):
    help = "Demo do'konlar, mahsulotlar, narx tarixi va buyurtmalarni yaratadi"

    @transaction.atomic
    def handle(self, *args, **opts):
        rnd = random.Random(42)  # takrorlanadigan natija uchun
        User = get_user_model()

        OrderItem.objects.all().delete()
        Order.objects.all().delete()
        PriceEntry.objects.all().delete()

        users = []
        for i in range(1, 6):
            u, created = User.objects.get_or_create(username=f"demo{i}")
            if created:
                u.set_password("demo12345")
                u.save()
            users.append(u)

        stores = []
        for name, k, _ in STORES:
            s, _ = Store.objects.update_or_create(
                slug=slugify(name), defaults={"name": name, "address": "Namangan sh.", "is_open": True}
            )
            stores.append((s, k))

        products = []
        for cat_name, items in PRODUCTS.items():
            cat, _ = Category.objects.get_or_create(slug=slugify(cat_name.replace("'", "")), defaults={"name": cat_name})
            for name, unit, base in items:
                p, _ = Product.objects.update_or_create(
                    slug=slugify(name.replace("'", "")), defaults={"name": name, "unit": unit, "category": cat}
                )
                # Har bir mahsulotga o'z narx trendi: -6%..+10% 45 kun davomida.
                products.append((p, base, rnd.uniform(-0.06, 0.10)))

        today = timezone.localdate()
        entries = []
        for store, k in stores:
            for product, base, trend in products:
                if rnd.random() < 0.1:  # ba'zi do'konlarda ba'zi mahsulot yo'q
                    continue
                store_k = k * rnd.uniform(0.96, 1.04)
                for d in range(DAYS, -1, -1):
                    if rnd.random() > 0.45:  # har kuni ham yozilmaydi
                        continue
                    day = today - timedelta(days=d)
                    progress = (DAYS - d) / DAYS
                    authors = rnd.sample(users, rnd.randint(1, 2))
                    for author in authors:
                        price = base * store_k * (1 + trend * progress) * rnd.uniform(0.97, 1.03)
                        entries.append(
                            PriceEntry(store=store, product=product, price=round100(price), date=day, author=author)
                        )
        PriceEntry.objects.bulk_create(entries)
        Discount.objects.all().delete()

        # Buyurtmalar: oxirgi 7 kunda STORES dagi son, undan oldin ham bir nechta (tarix uchun).
        from shop.stats import current_prices

        prices = current_prices()
        n_orders = 0
        for (store, _), (_, _, recent) in zip(stores, STORES):
            for i in range(recent + rnd.randint(1, 4)):
                old = i >= recent
                created = timezone.now() - timedelta(
                    days=rnd.uniform(8, 25) if old else rnd.uniform(0, 6.5)
                )
                order = Order.objects.create(
                    user=rnd.choice(users), store=store, phone="+998 90 000 00 00",
                    address="Namangan sh., demo manzil", status=rnd.choice(["new", "confirmed", "delivered"]),
                    created_at=created,
                )
                available = [p for p, _, _ in products if (store.id, p.id) in prices]
                for p in rnd.sample(available, rnd.randint(1, 4)):
                    OrderItem.objects.create(
                        order=order, product=p, unit_price=prices[(store.id, p.id)],
                        quantity=Decimal(rnd.choice(["0.5", "1", "1.5", "2", "3"])),
                    )
                n_orders += 1

        call_command("seed_discounts", stdout=self.stdout)
        call_command("seed_locations", stdout=self.stdout)

        self.stdout.write(self.style.SUCCESS(
            f"{len(stores)} do'kon, {len(products)} mahsulot, {len(entries)} narx yozuvi, {n_orders} buyurtma yaratildi. "
            "Demo login: demo1 / demo12345"
        ))
