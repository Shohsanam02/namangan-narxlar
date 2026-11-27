# Namangan narxlari

Namangandagi do'konlar (Korzinka, Makro, Havas, ...) narxlarini foydalanuvchilar yozib boradi.
Sayt qayerda arzonligini, narx qanday o'zgarayotganini, do'konlar reytingini va savdo faolligini ko'rsatadi;
mahsulotni tanlangan do'kondan onlayn buyurtma qilish mumkin (to'lov yetkazilganda).

## Imkoniyatlar

- Do'konlar paneli: har bir do'konning mahsulotlari va narxlari
- Chegirmalar: hozirgi va kutilayotgan
- Savat (miqdorni − / + bilan o'zgartirish), onlayn buyurtma, qayta buyurtma
- Yaqin do'konlar (masofa brauzerda hisoblanadi, joylashuv serverga yuborilmaydi)
- Haftalik narx hisoboti, sevimlilar, narx tushganda sayt ichida xabar
- "Narx to'g'rimi?" ovozi va narx rasmi (GPS kabi metama'lumot o'chiriladi)
- Yorug' va qorong'i mavzu

**Diqqat:** demo narxlar, chegirmalar va do'kon koordinatalari tasodifiy. Haqiqiy koordinatani `/admin/` da
kiriting va "Joylashuv tekshirilgan" belgisini qo'ying. Internetga chiqarishdan oldin demo akkauntlarni o'chiring,
`SECRET_KEY` ni almashtiring va `DEBUG=False` qiling.

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

- **Shubhali narx** — 👎 soni 👍 dan 3 taga ko'p bo'lsa, yozuv hisobdan chiqariladi.

Testlar: `python manage.py test shop`
