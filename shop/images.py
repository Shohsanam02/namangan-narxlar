"""Yuklangan rasmni xavfsiz holga keltirish."""
from io import BytesIO
from uuid import uuid4

from django.core.files.base import ContentFile
from PIL import Image, ImageOps

MAX_SIDE = 1600


def clean_photo(upload):
    """Rasmni qaytadan JPEG qilib yozadi.

    Nega: telefon rasmlari ichida GPS koordinata (EXIF) bo'ladi — uni ochiq saytga chiqarish
    foydalanuvchi joylashuvini oshkor qiladi. Qayta yozilganda metama'lumot tushib qoladi,
    hajm kichrayadi, fayl nomi ham tasodifiy bo'ladi.
    """
    upload.seek(0)
    with Image.open(upload) as img:
        img = ImageOps.exif_transpose(img)  # telefon rasmi yonboshlab qolmasligi uchun
        img = img.convert("RGB")
        img.thumbnail((MAX_SIDE, MAX_SIDE))
        out = BytesIO()
        img.save(out, "JPEG", quality=82)
    return ContentFile(out.getvalue(), name=f"{uuid4().hex}.jpg")
