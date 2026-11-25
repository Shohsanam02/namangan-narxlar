from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from . import stats
from .models import Category, Order, OrderItem, PriceEntry, Product, Store


class BaseData(TestCase):
    def setUp(self):
        User = get_user_model()
        self.users = [User.objects.create_user(f"u{i}", password="pass12345!") for i in range(3)]
        self.cat = Category.objects.create(name="Meva", slug="meva")
        self.olma = Product.objects.create(name="Olma", slug="olma", category=self.cat)
        self.banan = Product.objects.create(name="Banan", slug="banan", category=self.cat)
        self.cheap = Store.objects.create(name="Arzon", slug="arzon")
        self.mid = Store.objects.create(name="Orta", slug="orta")
        self.pricey = Store.objects.create(name="Qimmat", slug="qimmat")
        self.today = timezone.localdate()

    def price(self, store, product, value, days_ago=0, user=0):
        return PriceEntry.objects.create(
            store=store, product=product, price=Decimal(value),
            date=self.today - timedelta(days=days_ago), author=self.users[user],
        )


class CurrentPriceTests(BaseData):
    def test_median_ignores_outlier(self):
        # Ikki kishi 15 000, bittasi xato qilib 150 000 yozdi — median 15 000 bo'lishi kerak.
        self.price(self.cheap, self.olma, 15000, user=0)
        self.price(self.cheap, self.olma, 15000, user=1)
        self.price(self.cheap, self.olma, 150000, user=2)
        self.assertEqual(stats.current_prices()[(self.cheap.id, self.olma.id)], Decimal("15000"))

    def test_old_entries_outside_window_ignored(self):
        self.price(self.cheap, self.olma, 10000, days_ago=20)
        self.price(self.cheap, self.olma, 16000, days_ago=0)
        self.assertEqual(stats.current_prices()[(self.cheap.id, self.olma.id)], Decimal("16000"))

    def test_stale_prices_dropped(self):
        self.price(self.cheap, self.olma, 10000, days_ago=40)
        self.assertNotIn((self.cheap.id, self.olma.id), stats.current_prices())


class RankingTests(BaseData):
    def test_expensive_store_on_top(self):
        for product, base in ((self.olma, 10000), (self.banan, 20000)):
            self.price(self.cheap, product, base * 0.9)
            self.price(self.mid, product, base)
            self.price(self.pricey, product, base * 1.2)
        rows = stats.store_ranking()
        self.assertEqual([r["store"] for r in rows], [self.pricey, self.mid, self.cheap])
        self.assertEqual(rows[0]["index"], 120.0)
        self.assertEqual(rows[-1]["index"], 90.0)
        self.assertEqual(rows[-1]["cheapest"], 2)

    def test_store_without_comparison_goes_last(self):
        self.price(self.cheap, self.olma, 9000)
        self.price(self.mid, self.olma, 10000)
        rows = stats.store_ranking()
        self.assertIsNone(rows[-1]["index"])
        self.assertEqual(rows[-1]["store"], self.pricey)


class ActivityTests(BaseData):
    def make_orders(self, store, n, days_ago=1, status="new"):
        for _ in range(n):
            o = Order.objects.create(
                user=self.users[0], store=store, phone="1", address="x", status=status,
                created_at=timezone.now() - timedelta(days=days_ago),
            )
            OrderItem.objects.create(order=o, product=self.olma, unit_price=Decimal("1000"), quantity=Decimal("2"))

    def test_statuses(self):
        self.make_orders(self.cheap, stats.ACTIVE_MIN_ORDERS)
        self.make_orders(self.mid, 1)
        self.make_orders(self.pricey, 10, days_ago=30)  # eski buyurtmalar hisoblanmaydi
        a = stats.store_activity(Store.objects.all())
        self.assertEqual(a[self.cheap.id]["status"], "Faol")
        self.assertEqual(a[self.cheap.id]["revenue"], Decimal("10000"))
        self.assertEqual(a[self.mid.id]["status"], "Sust")
        self.assertEqual(a[self.pricey.id]["status"], "Faolsiz")

    def test_cancelled_not_counted_and_closed_store_inactive(self):
        self.make_orders(self.cheap, 6, status="cancelled")
        self.make_orders(self.mid, 6)
        self.mid.is_open = False
        self.mid.save()
        a = stats.store_activity(Store.objects.all())
        self.assertEqual(a[self.cheap.id]["orders"], 0)
        self.assertEqual(a[self.mid.id]["status"], "Faolsiz")


class OrderFlowTests(BaseData):
    def test_cart_to_order_snapshots_price(self):
        self.price(self.cheap, self.olma, 12000)
        self.client.login(username="u0", password="pass12345!")
        self.client.post(reverse("cart_add"), {"store": self.cheap.id, "product": self.olma.id, "qty": "1,5"})
        resp = self.client.post(reverse("checkout", args=[self.cheap.id]), {"phone": "+998901234567", "address": "Namangan"})
        self.assertRedirects(resp, reverse("my_orders"))
        order = Order.objects.get()
        item = order.items.get()
        self.assertEqual(item.unit_price, Decimal("12000"))
        self.assertEqual(order.total, Decimal("18000"))
        # Narx keyin o'zgarsa ham buyurtma summasi o'zgarmaydi.
        self.price(self.cheap, self.olma, 99000, user=1)
        self.assertEqual(Order.objects.get().total, Decimal("18000"))
        self.assertEqual(self.client.session["cart"], {})

    def test_cannot_add_without_current_price(self):
        self.client.post(reverse("cart_add"), {"store": self.cheap.id, "product": self.olma.id, "qty": "1"})
        self.assertEqual(self.client.session.get("cart", {}), {})

    def test_checkout_requires_login(self):
        resp = self.client.get(reverse("checkout", args=[self.cheap.id]))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("login"), resp.url)

    def test_add_price_same_day_updates(self):
        self.client.login(username="u0", password="pass12345!")
        data = {"store": self.cheap.id, "product": self.olma.id, "price": "10000", "date": self.today.isoformat()}
        self.client.post(reverse("add_price"), data)
        self.client.post(reverse("add_price"), {**data, "price": "11000"})
        self.assertEqual(PriceEntry.objects.count(), 1)
        self.assertEqual(PriceEntry.objects.get().price, Decimal("11000"))


class PagesSmokeTests(BaseData):
    def test_pages_render(self):
        self.price(self.cheap, self.olma, 9000)
        self.price(self.mid, self.olma, 10000)
        for url in [
            reverse("home"), reverse("statistics"), reverse("cart"),
            reverse("product_detail", args=["olma"]), reverse("store_detail", args=["arzon"]),
        ]:
            self.assertEqual(self.client.get(url).status_code, 200, url)
