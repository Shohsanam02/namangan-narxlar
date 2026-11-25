from django import forms
from django.contrib.auth.forms import UserCreationForm

from .models import Order, PriceEntry


class PriceEntryForm(forms.ModelForm):
    class Meta:
        model = PriceEntry
        fields = ["store", "product", "price", "date"]
        widgets = {"date": forms.DateInput(attrs={"type": "date"})}

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


class SignUpForm(UserCreationForm):
    pass
