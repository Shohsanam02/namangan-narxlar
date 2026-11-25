from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("mahsulot/<slug:slug>/", views.product_detail, name="product_detail"),
    path("dokon/<slug:slug>/", views.store_detail, name="store_detail"),
    path("statistika/", views.statistics, name="statistics"),
    path("narx-yozish/", views.add_price, name="add_price"),
    path("savat/", views.cart_view, name="cart"),
    path("savat/qoshish/", views.cart_add, name="cart_add"),
    path("savat/olib-tashlash/", views.cart_remove, name="cart_remove"),
    path("buyurtma/<int:store_id>/", views.checkout, name="checkout"),
    path("buyurtmalarim/", views.my_orders, name="my_orders"),
    path("royxatdan-otish/", views.signup, name="signup"),
]
