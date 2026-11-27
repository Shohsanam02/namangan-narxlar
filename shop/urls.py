from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("mahsulot/<slug:slug>/", views.product_detail, name="product_detail"),
    path("dokon/<slug:slug>/", views.store_detail, name="store_detail"),
    path("narx/<int:entry_id>/ovoz/", views.vote_price, name="vote_price"),
    path("sevimlilar/", views.favorites, name="favorites"),
    path("sevimlilar/<int:product_id>/", views.toggle_favorite, name="toggle_favorite"),
    path("xabarlar/", views.alerts, name="alerts"),
    path("xabarlar/qoshish/<int:product_id>/", views.set_alert, name="set_alert"),
    path("xabarlar/ochirish/<int:alert_id>/", views.delete_alert, name="delete_alert"),
    path("qayta-buyurtma/<int:order_id>/", views.reorder, name="reorder"),
    path("haftalik/", views.weekly, name="weekly"),
    path("yaqin/", views.nearby, name="nearby"),
    path("chegirmalar/", views.discounts, name="discounts"),
    path("statistika/", views.statistics, name="statistics"),
    path("narx-yozish/", views.add_price, name="add_price"),
    path("savat/", views.cart_view, name="cart"),
    path("savat/qoshish/", views.cart_add, name="cart_add"),
    path("savat/miqdor/", views.cart_change, name="cart_change"),
    path("savat/olib-tashlash/", views.cart_remove, name="cart_remove"),
    path("buyurtma/<int:store_id>/", views.checkout, name="checkout"),
    path("buyurtmalarim/", views.my_orders, name="my_orders"),
    path("royxatdan-otish/", views.signup, name="signup"),
]
