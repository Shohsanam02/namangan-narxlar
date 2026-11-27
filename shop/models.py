from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


class Store(models.Model):
    """Namangandagi do'kon (Korzinka, Makro, ...)."""

    name = models.CharField("Nomi", max_length=100, unique=True)
    slug = models.SlugField(unique=True)
    address = models.CharField("Manzil", max_length=200, blank=True)
    is_open = models.BooleanField("Buyurtma qabul qiladi", default=True)
    latitude = models.DecimalField(
        "Kenglik (latitude)", max_digits=9, decimal_places=6, null=True, blank=True,
        validators=[MinValueValidator(-90), MaxValueValidator(90)],
    )
    longitude = models.DecimalField(
        "Uzunlik (longitude)", max_digits=9, decimal_places=6, null=True, blank=True,
        validators=[MinValueValidator(-180), MaxValueValidator(180)],
    )
    # Tasdiqlanmagan nuqtaga "yo'l ko'rsatish" berilmaydi — odamni noto'g'ri joyga yubormaslik uchun.
    location_verified = models.BooleanField("Joylashuv tekshirilgan", default=False)

    class Meta:
        ordering = ["name"]
        verbose_name = "Do'kon"
        verbose_name_plural = "Do'konlar"

    def __str__(self):
        return self.name

    def clean(self):
        if (self.latitude is None) != (self.longitude is None):
            raise ValidationError("Kenglik va uzunlik ikkalasi ham kiritilishi kerak.")
        if self.location_verified and self.latitude is None:
            raise ValidationError("Koordinatasiz joylashuvni tekshirilgan deb belgilab bo'lmaydi.")


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
    photo = models.ImageField("Narx yorlig'i rasmi (ixtiyoriy)", upload_to="prices/%Y/%m/", blank=True)

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


class Discount(models.Model):
    """Do'kondagi mahsulotga ma'lum muddatli chegirma.

    Foizda saqlanadi: joriy narx foydalanuvchi yozuvlaridan o'zgarib turadi,
    qat'iy "chegirma narxi" esa tezda eskirib qolardi.
    """

    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="discounts", verbose_name="Do'kon")
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="discounts", verbose_name="Mahsulot")
    percent = models.PositiveSmallIntegerField(
        "Chegirma (%)", validators=[MinValueValidator(1), MaxValueValidator(90)]
    )
    start_date = models.DateField("Boshlanadi")
    end_date = models.DateField("Tugaydi (shu kun ham kiradi)")

    class Meta:
        ordering = ["start_date", "store__name"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(end_date__gte=models.F("start_date")), name="discount_end_after_start"
            )
        ]
        verbose_name = "Chegirma"
        verbose_name_plural = "Chegirmalar"

    def __str__(self):
        return f"{self.store}: {self.product} -{self.percent}% ({self.start_date} - {self.end_date})"

    def clean(self):
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValidationError({"end_date": "Tugash sanasi boshlanishdan oldin bo'lishi mumkin emas."})


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


class PriceVote(models.Model):
    """"Narx to'g'rimi?" ovozi. Bitta foydalanuvchi bitta yozuvga bitta ovoz beradi."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="price_votes")
    entry = models.ForeignKey(PriceEntry, on_delete=models.CASCADE, related_name="votes")
    is_correct = models.BooleanField("To'g'ri")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "entry"], name="one_vote_per_user_entry")]
        verbose_name = "Narx ovozi"
        verbose_name_plural = "Narx ovozlari"


class Favorite(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="favorites")
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="favorites")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "product"], name="one_favorite_per_user")]


class PriceAlert(models.Model):
    """"Narx shu summadan arzonlashsa xabar ber".

    Xabar bazada saqlanmaydi: shart sahifa ochilganda tekshiriladi, shuning uchun fon jarayoni kerak emas.
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="price_alerts")
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="alerts")
    target_price = models.DecimalField(
        "Kutilgan narx (so'm)", max_digits=12, decimal_places=0, validators=[MinValueValidator(Decimal("1"))]
    )

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "product"], name="one_alert_per_user_product")]
