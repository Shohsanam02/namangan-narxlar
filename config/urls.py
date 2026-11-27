from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("django.contrib.auth.urls")),
    path("", include("shop.urls")),
]

# Faqat DEBUG rejimida ishlaydi; productionda rasmlarni veb-server yoki bulut xotira beradi.
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
