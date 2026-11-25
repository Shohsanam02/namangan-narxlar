"""Sessiyadagi savat. Kalit: "store_id:product_id", qiymat: miqdor (str, Decimal uchun).

Nega sessiya, DB emas: ro'yxatdan o'tmagan foydalanuvchi ham savat yig'a oladi,
buyurtma berishda esa login so'raladi.
"""
from decimal import Decimal, InvalidOperation

SESSION_KEY = "cart"


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
    if qty <= 0 or qty > 1000:
        return None
    return qty.quantize(Decimal("0.01"))
