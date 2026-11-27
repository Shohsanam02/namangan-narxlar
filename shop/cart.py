"""Sessiyadagi savat. Kalit: "store_id:product_id", qiymat: miqdor (str, Decimal uchun).

Nega sessiya, DB emas: ro'yxatdan o'tmagan foydalanuvchi ham savat yig'a oladi,
buyurtma berishda esa login so'raladi.
"""
from decimal import Decimal, InvalidOperation

SESSION_KEY = "cart"
MAX_QTY = 1000


class Cart:
    def __init__(self, request):
        self.session = request.session
        self.data = self.session.setdefault(SESSION_KEY, {})

    def _save(self):
        self.session.modified = True

    def add(self, store_id, product_id, qty):
        key = f"{store_id}:{product_id}"
        current = Decimal(self.data.get(key, "0"))
        self.data[key] = str(current + qty)
        self._save()

    def set(self, store_id, product_id, qty):
        self.data[f"{store_id}:{product_id}"] = str(min(qty, MAX_QTY))
        self._save()

    def change(self, store_id, product_id, delta):
        """Savatdagi miqdorni delta ga o'zgartiradi.

        Natija 0 yoki manfiy bo'lsa yoki chegaradan oshsa, hech narsa o'zgarmaydi:
        mahsulotni o'chirish faqat ✕ tugmasi bilan, tasodifan minus bosib yo'qotmaslik uchun.
        """
        key = f"{store_id}:{product_id}"
        if key not in self.data:
            return
        qty = Decimal(self.data[key]) + delta
        if 0 < qty <= MAX_QTY:
            self.data[key] = str(qty)
            self._save()

    def remove(self, store_id, product_id):
        self.data.pop(f"{store_id}:{product_id}", None)
        self._save()

    def clear_store(self, store_id):
        for key in [k for k in self.data if k.startswith(f"{store_id}:")]:
            del self.data[key]
        self._save()

    def items(self):
        for key, qty in self.data.items():
            store_id, product_id = map(int, key.split(":"))
            yield store_id, product_id, Decimal(qty)

    def __len__(self):
        return len(self.data)


def parse_qty(raw):
    try:
        qty = Decimal(str(raw).replace(",", "."))
    except InvalidOperation:
        return None
    if qty <= 0 or qty > MAX_QTY:
        return None
    return qty.quantize(Decimal("0.01"))
