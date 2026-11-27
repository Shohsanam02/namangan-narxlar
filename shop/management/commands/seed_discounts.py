"""Demo chegirmalar (TAXMINIY, haqiqiy aksiyalar emas). Narx va buyurtmalarga tegmaydi."""
import random
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from shop.models import Discount
from shop.stats import current_prices


class Command(BaseCommand):
    help = "Har bir do'konga amaldagi va kutilayotgan demo chegirmalar qo'shadi"

    def handle(self, *args, **opts):
        # Mavjud chegirmalar (admin qo'shganlari ham) o'chirilmaydi.
        if Discount.objects.exists():
            self.stdout.write("Chegirmalar allaqachon bor — hech narsa qo'shilmadi.")
            return

        rnd = random.Random(7)
        today = timezone.localdate()
        by_store = {}
        for store_id, product_id in sorted(current_prices()):
            by_store.setdefault(store_id, []).append(product_id)

        rows = []
        for store_id, product_ids in by_store.items():
            picked = rnd.sample(product_ids, min(5, len(product_ids)))
            # 3 tasi hozir amalda, 2 tasi keyinroq boshlanadi
            for i, product_id in enumerate(picked):
                start = today - timedelta(days=rnd.randint(0, 3)) if i < 3 else today + timedelta(days=rnd.randint(1, 10))
                rows.append(
                    Discount(
                        store_id=store_id, product_id=product_id, percent=rnd.choice([5, 10, 15, 20]),
                        start_date=start, end_date=max(start, today) + timedelta(days=rnd.randint(2, 7)),
                    )
                )
        Discount.objects.bulk_create(rows)
        self.stdout.write(self.style.SUCCESS(f"{len(rows)} ta demo chegirma qo'shildi."))
