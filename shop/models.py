from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone


class Store(models.Model):
    """Namangandagi do'kon (Korzinka, Makro, ...)."""

    name = models.CharField("Nomi", max_length=100, unique=True)
    slug = models.SlugField(unique=True)
    address = models.CharField("Manzil", max_length=200, blank=True)
    is_open = models.BooleanField("Buyurtma qabul qiladi", default=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Do'kon"
        verbose_name_plural = "Do'konlar"

    def __str__(self):
        return self.name


class Category(models.Model):
    name = models.CharField("Nomi", max_length=60, unique=True)
    slug = models.SlugField(unique=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Kategoriya"
        verbose_name_plural = "Kategoriyalar"

    def __str__(self):
        return self.name


class Product(models.Model):
    UNIT_CHOICES = [("kg", "kg"), ("dona", "dona"), ("litr", "litr"), ("bog'", "bog'")]

    name = models.CharField("Nomi", max_length=100, unique=True)
    slug = models.SlugField(unique=True)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="products")
    unit = models.CharField("O'lchov", max_length=10, choices=UNIT_CHOICES, default="kg")

    class Meta:
        ordering = ["name"]
        verbose_name = "Mahsulot"
        verbose_name_plural = "Mahsulotlar"

    def __str__(self):
        return self.name


class PriceEntry(models.Model):
    """Foydalanuvchi yozgan narx. Narx tarixi shu jadvaldan quriladi."""

    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="prices")
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="prices")
    price = models.DecimalField(
        "Narx (so'm)", max_digits=12, decimal_places=0, validators=[MinValueValidator(Decimal("1"))]
    )
    date = models.DateField("Sana", default=timezone.localdate)
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="price_entries"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-created_at"]
        indexes = [models.Index(fields=["product", "store", "-date"])]
        constraints = [
            # Bitta foydalanuvchi bir kunda bir do'kondagi bir mahsulotga faqat bitta narx yozadi —
            # spam/xato dublikatlar statistikani buzmasligi uchun.
            models.UniqueConstraint(fields=["author", "store", "product", "date"], name="one_price_per_user_day")
        ]
        verbose_name = "Narx yozuvi"
        verbose_name_plural = "Narx yozuvlari"

    def __str__(self):
        return f"{self.product} @ {self.store}: {self.price} ({self.date})"


class Order(models.Model):
    STATUS_CHOICES = [
        ("new", "Yangi"),
        ("confirmed", "Tasdiqlandi"),
        ("delivered", "Yetkazildi"),
        ("cancelled", "Bekor qilindi"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="orders")
    store = models.ForeignKey(Store, on_delete=models.PROTECT, related_name="orders")
    phone = models.CharField("Telefon", max_length=20)
    address = models.CharField("Yetkazish manzili", max_length=255)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default="new")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Buyurtma"
        verbose_name_plural = "Buyurtmalar"

    def __str__(self):
        return f"#{self.pk} {self.store} — {self.user}"

    @property
    def total(self):
        return sum((i.subtotal for i in self.items.all()), Decimal("0"))


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    # Narx buyurtma paytidagi qiymat bilan saqlanadi: keyin narx o'zgarsa ham chek o'zgarmasligi kerak.
    unit_price = models.DecimalField(max_digits=12, decimal_places=0)
    quantity = models.DecimalField(max_digits=8, decimal_places=2, validators=[MinValueValidator(Decimal("0.1"))])

    @property
    def subtotal(self):
        return self.unit_price * self.quantity
