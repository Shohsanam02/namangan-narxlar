# Namangan narxlari

Namangandagi do'konlar (Korzinka, Makro, Havas, ...) narxlarini foydalanuvchilar yozib boradi.
Sayt qayerda arzonligini, narx qanday o'zgarayotganini, do'konlar reytingini va savdo faolligini ko'rsatadi;
mahsulotni tanlangan do'kondan onlayn buyurtma qilish mumkin (to'lov yetkazilganda).

## Ishga tushirish

    python -m venv .venv
    .venv\Scripts\activate
    pip install -r requirements.txt
    python manage.py migrate
    python manage.py seed_demo        # demo ma'lumot (narxlar TAXMINIY, haqiqiy emas)
    python manage.py createsuperuser  # /admin/ uchun
    python manage.py runserver

Demo login: `demo1` / `demo12345`.

## Asosiy hisoblar (shop/stats.py)

- **Joriy narx** — do'kon+mahsulot juftligining oxirgi 7 kundagi yozuvlari medianasi (xato yozuvlarga chidamli).
- **Narx indeksi** — har bir mahsulot narxi / shu mahsulotning barcha do'konlardagi medianasi, o'rtachasi x 100.
  Reytingda eng qimmat do'kon tepada.
- **Savdo holati** — oxirgi 7 kundagi (bekor qilinmagan) buyurtmalar: 5+ Faol, 1-4 Sust, 0 yoki do'kon yopiq — Faolsiz.

Testlar: `python manage.py test shop`
