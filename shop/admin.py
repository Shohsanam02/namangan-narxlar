from django.contrib import admin

from .models import Category, Discount, Order, OrderItem, PriceEntry, PriceVote, Product, Store


@admin.register(Store)
class StoreAdmin(admin.ModelAdmin):
    list_display = ["name", "address", "is_open", "latitude", "longitude", "location_verified"]
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
    list_display = ["product", "store", "price", "date", "author", "photo"]
    list_filter = ["store", "product__category", "date"]
    autocomplete_fields = []


@admin.register(Discount)
class DiscountAdmin(admin.ModelAdmin):
    list_display = ["product", "store", "percent", "start_date", "end_date"]
    list_filter = ["store", "start_date"]


@admin.register(PriceVote)
class PriceVoteAdmin(admin.ModelAdmin):
    list_display = ["entry", "user", "is_correct"]
    list_filter = ["is_correct"]


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ["id", "store", "user", "status", "created_at"]
    list_filter = ["status", "store"]
    list_editable = ["status"]
    inlines = [OrderItemInline]
