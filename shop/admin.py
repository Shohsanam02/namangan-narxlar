from django.contrib import admin

from .models import Category, Order, OrderItem, PriceEntry, Product, Store


@admin.register(Store)
class StoreAdmin(admin.ModelAdmin):
    list_display = ["name", "address", "is_open"]
    list_editable = ["is_open"]
    prepopulated_fields = {"slug": ["name"]}


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    prepopulated_fields = {"slug": ["name"]}


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ["name", "category", "unit"]
    list_filter = ["category"]
    prepopulated_fields = {"slug": ["name"]}


@admin.register(PriceEntry)
class PriceEntryAdmin(admin.ModelAdmin):
    list_display = ["product", "store", "price", "date", "author"]
    list_filter = ["store", "product__category", "date"]
    autocomplete_fields = []


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ["id", "store", "user", "status", "created_at"]
    list_filter = ["status", "store"]
    list_editable = ["status"]
    inlines = [OrderItemInline]
