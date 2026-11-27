from datetime import timedelta

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.utils import timezone

from .models import Order, PriceAlert, PriceEntry

MAX_PHOTO_BYTES = 5 * 1024 * 1024
# Eski sanalarga soxta narx yozib, narx tarixini buzib bo'lmasligi uchun.
MAX_BACKDATE_DAYS = 7


class PriceEntryForm(forms.ModelForm):
    class Meta:
        model = PriceEntry
        fields = ["store", "product", "price", "date", "photo"]
        labels = {"store": "Do'kon", "product": "Mahsulot"}
        widgets = {
            # type="date" faqat YYYY-MM-DD qabul qiladi; "uz" formatida maydon bo'sh ko'rinardi.
            "date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "photo": forms.FileInput(attrs={"accept": "image/jpeg,image/png,image/webp"}),
        }

    def clean_date(self):
        date = self.cleaned_data["date"]
        today = timezone.localdate()
        if date > today:
            raise forms.ValidationError("Kelajak sanasiga narx yozib bo'lmaydi.")
        if date < today - timedelta(days=MAX_BACKDATE_DAYS):
            raise forms.ValidationError(f"Faqat oxirgi {MAX_BACKDATE_DAYS} kundagi narxni yozish mumkin.")
        return date

    def clean_photo(self):
        photo = self.cleaned_data.get("photo")
        if photo and photo.size > MAX_PHOTO_BYTES:
            raise forms.ValidationError("Rasm 5 MB dan katta bo'lmasin.")
        return photo

    def clean_price(self):
        price = self.cleaned_data["price"]
        if price > 10_000_000:
            raise forms.ValidationError("Narx juda katta — xato yozilmaganmi?")
        return price


class CheckoutForm(forms.ModelForm):
    class Meta:
        model = Order
        fields = ["phone", "address"]
        widgets = {"phone": forms.TextInput(attrs={"placeholder": "+998 90 123 45 67"})}


class PriceAlertForm(forms.ModelForm):
    class Meta:
        model = PriceAlert
        fields = ["target_price"]


class SignUpForm(UserCreationForm):
    pass
