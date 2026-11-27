"""Koordinatasi yo'q do'konlarga DEMO nuqta qo'yadi (Namangan markazi atrofida, TASODIFIY).

Bular do'konlarning haqiqiy manzili EMAS. Haqiqiy koordinatani /admin/ da kiriting
va "Joylashuv tekshirilgan" belgisini qo'ying.
"""
import random
from decimal import Decimal

from django.core.management.base import BaseCommand

from shop.models import Store

CENTER_LAT, CENTER_LNG = 40.9983, 71.6726


class Command(BaseCommand):
    help = "Koordinatasi yo'q do'konlarga demo nuqta qo'yadi"

    def handle(self, *args, **opts):
        n = 0
        for store in Store.objects.filter(latitude__isnull=True):
            rnd = random.Random(store.slug)  # har ishga tushirishda bir xil nuqta
            store.latitude = Decimal(f"{CENTER_LAT + rnd.uniform(-0.02, 0.02):.6f}")
            store.longitude = Decimal(f"{CENTER_LNG + rnd.uniform(-0.025, 0.025):.6f}")
            store.location_verified = False
            store.save(update_fields=["latitude", "longitude", "location_verified"])
            n += 1
        self.stdout.write(self.style.SUCCESS(f"{n} ta do'konga demo joylashuv qo'yildi."))
