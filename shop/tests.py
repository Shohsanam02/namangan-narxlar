import tempfile
from datetime import timedelta
from decimal import Decimal
from io import BytesIO, StringIO

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from . import stats
from .models import (
    Category, Discount, Favorite, Order, OrderItem, PriceAlert, PriceEntry, PriceVote, Product, Store,
)


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


class DiscountTests(BaseData):
    def discount(self, percent, start=0, end=3, store=None):
        return Discount.objects.create(
            store=store or self.cheap, product=self.olma, percent=percent,
            start_date=self.today + timedelta(days=start), end_date=self.today + timedelta(days=end),
        )

    def test_only_current_discount_applies_and_biggest_wins(self):
        self.price(self.cheap, self.olma, 10000)
        self.discount(10)
        self.discount(20, start=0, end=0)    # oxirgi kuni ham amalda
        self.discount(50, start=2, end=5)    # hali boshlanmagan
        self.discount(60, start=-9, end=-1)  # tugagan
        info = stats.effective_prices()[(self.cheap.id, self.olma.id)]
        self.assertEqual((info["price"], info["base"]), (Decimal("8000"), Decimal("10000")))
        active, upcoming = stats.discount_rows()
        self.assertEqual(sorted(r["discount"].percent for r in active), [10, 20])
        self.assertEqual([r["discount"].percent for r in upcoming], [50])

    def test_order_uses_discounted_price(self):
        self.price(self.cheap, self.olma, 10000)
        self.discount(15)
        self.client.login(username="u0", password="pass12345!")
        self.client.post(reverse("cart_add"), {"store": self.cheap.id, "product": self.olma.id, "qty": "2"})
        self.client.post(reverse("checkout", args=[self.cheap.id]), {"phone": "1", "address": "x"})
        self.assertEqual(Order.objects.get().total, Decimal("17000"))

    def test_discount_changes_cheapest_but_not_price_index(self):
        self.price(self.cheap, self.olma, 10000)
        self.price(self.mid, self.olma, 11000)
        self.discount(20, store=self.mid)
        self.assertEqual(stats.cheapest_by_product()[0]["min_store"], self.mid)
        rows = stats.store_ranking()
        self.assertEqual(rows[0]["store"], self.mid)  # reyting asl narx bo'yicha

    def test_end_before_start_invalid(self):
        d = Discount(store=self.cheap, product=self.olma, percent=10,
                     start_date=self.today, end_date=self.today - timedelta(days=1))
        with self.assertRaises(ValidationError):
            d.full_clean()

    def test_pages_show_only_selected_store(self):
        self.price(self.cheap, self.olma, 10000)
        self.price(self.mid, self.banan, 20000)
        self.discount(10)
        resp = self.client.get(reverse("store_detail", args=["arzon"]))
        self.assertEqual([i["product"] for i in resp.context["items"]], [self.olma])
        self.assertContains(resp, "-10%")
        self.assertContains(self.client.get(reverse("discounts")), "-10%")


class CartStepperTests(BaseData):
    def test_plus_minus(self):
        self.price(self.cheap, self.olma, 1000)
        ids = {"store": self.cheap.id, "product": self.olma.id}
        key = f"{self.cheap.id}:{self.olma.id}"
        self.client.post(reverse("cart_add"), {**ids, "qty": "1"})

        def step(action):
            self.client.post(reverse("cart_change"), {**ids, "action": action})
            return Decimal(self.client.session["cart"][key])

        self.assertEqual(step("plus"), 2)
        self.assertEqual(step("minus"), 1)
        self.assertEqual(step("minus"), 1)  # 1 dan pastga tushmaydi, o'chib ketmaydi
        self.assertEqual(step("boshqa"), 1)

    def test_change_does_not_create_items(self):
        self.client.post(reverse("cart_change"), {"store": 1, "product": 1, "action": "plus"})
        self.assertEqual(self.client.session.get("cart", {}), {})


class NearbyTests(BaseData):
    def test_page_splits_located_stores_and_hides_unverified_route(self):
        Store.objects.filter(pk=self.cheap.pk).update(latitude=Decimal("41.001000"), longitude=Decimal("71.670000"))
        Store.objects.filter(pk=self.mid.pk).update(
            latitude=Decimal("41.002000"), longitude=Decimal("71.671000"), location_verified=True
        )
        resp = self.client.get(reverse("nearby"))
        self.assertEqual({r["store"] for r in resp.context["located"]}, {self.cheap, self.mid})
        self.assertEqual([r["store"] for r in resp.context["unlocated"]], [self.pricey])
        # Yo'l havolasi faqat tekshirilgan do'konda; koordinata nuqta bilan (vergul emas) chiqadi.
        self.assertContains(resp, "google.com/maps/dir/", count=1)
        self.assertContains(resp, "destination=41.002000,71.671000")
        self.assertContains(resp, 'data-lat="41.001000"')

    def test_seed_locations_keeps_existing_coordinates(self):
        Store.objects.filter(pk=self.cheap.pk).update(latitude=Decimal("1"), longitude=Decimal("2"))
        call_command("seed_locations", verbosity=0, stdout=StringIO())
        self.cheap.refresh_from_db()
        self.mid.refresh_from_db()
        self.assertEqual(self.cheap.latitude, Decimal("1"))
        self.assertIsNotNone(self.mid.latitude)
        self.assertFalse(self.mid.location_verified)

    def test_coordinates_must_come_in_pairs(self):
        self.cheap.latitude = Decimal("41")
        with self.assertRaises(ValidationError):
            self.cheap.full_clean()


class VoteTests(BaseData):
    def setUp(self):
        super().setUp()
        User = get_user_model()
        self.voters = [User.objects.create_user(f"v{i}", password="pass12345!") for i in range(3)]
        self.good = self.price(self.cheap, self.olma, 10000, user=0)
        self.bad = self.price(self.cheap, self.olma, 90000, user=1)

    def vote(self, user, entry, value):
        self.client.force_login(user)
        return self.client.post(reverse("vote_price", args=[entry.id]), {"vote": value})

    def test_three_dislikes_hide_price_from_stats(self):
        pair = (self.cheap.id, self.olma.id)
        for voter in self.voters[:2]:
            self.vote(voter, self.bad, "no")
        self.assertEqual(stats.current_prices()[pair], Decimal("50000"))
        self.vote(self.voters[2], self.bad, "no")
        self.assertEqual(stats.current_prices()[pair], Decimal("10000"))
        self.assertContains(self.client.get(reverse("product_detail", args=["olma"])), "shubhali")

    def test_one_vote_per_user_toggle_and_no_self_vote(self):
        self.vote(self.voters[0], self.bad, "no")
        self.vote(self.voters[0], self.bad, "yes")
        self.assertEqual([v.is_correct for v in PriceVote.objects.all()], [True])
        self.vote(self.voters[0], self.bad, "yes")
        self.assertEqual(PriceVote.objects.count(), 0)
        self.vote(self.users[1], self.bad, "yes")  # o'z yozuvi
        self.assertEqual(PriceVote.objects.count(), 0)

    def test_changing_price_resets_votes(self):
        self.vote(self.voters[0], self.bad, "no")
        self.client.force_login(self.users[1])
        self.client.post(reverse("add_price"), {
            "store": self.cheap.id, "product": self.olma.id, "price": "11000", "date": self.today.isoformat()})
        self.assertEqual(PriceVote.objects.count(), 0)


class DateAndPhotoTests(BaseData):
    def post(self, **extra):
        self.client.force_login(self.users[0])
        data = {"store": self.cheap.id, "product": self.olma.id, "price": "10000", "date": self.today.isoformat()}
        return self.client.post(reverse("add_price"), {**data, **extra})

    def test_future_and_old_dates_rejected(self):
        for days in (1, -8):
            self.post(date=(self.today + timedelta(days=days)).isoformat())
        self.assertEqual(PriceEntry.objects.count(), 0)

    def test_photo_is_reencoded_without_gps_metadata(self):
        buf = BytesIO()
        exif = Image.Exif()
        exif[0x010F] = "MaxfiyKamera"
        Image.new("RGB", (3000, 1000), "red").save(buf, "JPEG", exif=exif)
        with tempfile.TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            self.post(photo=SimpleUploadedFile("uy_manzilim.jpg", buf.getvalue(), "image/jpeg"))
            entry = PriceEntry.objects.get()
            self.assertNotIn("manzil", entry.photo.name)
            with Image.open(entry.photo.path) as img:
                self.assertEqual(img.size, (1600, 533))
                self.assertEqual(len(img.getexif()), 0)

    def test_non_image_rejected(self):
        resp = self.post(photo=SimpleUploadedFile("x.jpg", b"<script>alert(1)</script>", "image/jpeg"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(PriceEntry.objects.count(), 0)


class FavoriteAlertReorderTests(BaseData):
    def setUp(self):
        super().setUp()
        self.price(self.cheap, self.olma, 10000)
        self.client.force_login(self.users[0])

    def test_favorite_toggle_and_safe_redirect(self):
        url = reverse("toggle_favorite", args=[self.olma.id])
        resp = self.client.post(url, {"next": "https://yomon.example/"})
        self.assertEqual(resp.url, reverse("favorites"))
        self.assertContains(self.client.get(reverse("favorites")), "Olma")
        self.client.post(url)
        self.assertEqual(Favorite.objects.count(), 0)

    def test_alert_triggers_only_at_target(self):
        url = reverse("set_alert", args=[self.olma.id])
        self.client.post(url, {"target_price": "9000"})
        self.assertEqual(self.client.get(reverse("alerts")).context["alert_count"], 0)
        self.client.post(url, {"target_price": "10000"})
        self.assertEqual(PriceAlert.objects.count(), 1)
        self.assertEqual(self.client.get(reverse("alerts")).context["alert_count"], 1)

    def test_cannot_delete_others_alert_or_reorder_others_order(self):
        alert = PriceAlert.objects.create(user=self.users[1], product=self.olma, target_price=1)
        order = Order.objects.create(user=self.users[1], store=self.cheap, phone="1", address="x")
        self.assertEqual(self.client.post(reverse("delete_alert", args=[alert.id])).status_code, 404)
        self.assertEqual(self.client.post(reverse("reorder", args=[order.id])).status_code, 404)

    def test_reorder_sets_quantity_and_skips_unpriced(self):
        order = Order.objects.create(user=self.users[0], store=self.cheap, phone="1", address="x")
        for product in (self.olma, self.banan):
            OrderItem.objects.create(order=order, product=product, unit_price=1, quantity=Decimal("2"))
        for _ in range(2):
            self.client.post(reverse("reorder", args=[order.id]))
        self.assertEqual(self.client.session["cart"], {f"{self.cheap.id}:{self.olma.id}": "2.00"})


class ReportTests(BaseData):
    def test_weekly_compares_same_stores_only(self):
        self.price(self.cheap, self.olma, 10000, days_ago=8)
        self.price(self.cheap, self.olma, 12000)
        self.price(self.pricey, self.olma, 99000)  # bu hafta qo'shilgan do'kon hisobga kirmaydi
        up, down = stats.weekly_report()
        self.assertEqual((up[0]["change"], down), (20.0, []))

    def test_pages_render(self):
        for name in ("weekly", "home"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200)


class AddPriceFormTests(BaseData):
    def test_date_prefilled_in_iso_format(self):
        self.client.force_login(self.users[0])
        self.assertContains(self.client.get(reverse("add_price")), f'value="{self.today.isoformat()}"')
