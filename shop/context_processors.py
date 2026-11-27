from . import stats
from .cart import Cart


def cart(request):
    user = getattr(request, "user", None)
    alerts = 0
    if user and user.is_authenticated:
        alerts = sum(r["triggered"] for r in stats.alert_rows(user))
    return {"cart_count": len(Cart(request)), "alert_count": alerts}
