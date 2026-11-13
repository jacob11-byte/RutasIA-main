from functools import wraps

from logistics.models import UserProfile
from logistics.presentation.serializers import _require_role


ADMIN = UserProfile.Role.ADMIN
SUPERVISOR = UserProfile.Role.SUPERVISOR
SELLER = UserProfile.Role.SELLER
DRIVER = UserProfile.Role.DRIVER
WRITE_ROLES = {
    "api_users": (ADMIN,), "api_user_detail": (ADMIN,),
    "api_departments": (ADMIN, SUPERVISOR), "api_stores": (ADMIN, SUPERVISOR, SELLER),
    "api_store_detail": (ADMIN, SUPERVISOR, SELLER),
    "api_products": (ADMIN, SUPERVISOR), "api_product_detail": (ADMIN, SUPERVISOR),
    "api_inventory": (ADMIN, SUPERVISOR), "api_drivers": (ADMIN, SUPERVISOR),
    "api_vehicles": (ADMIN, SUPERVISOR), "api_orders": (ADMIN, SUPERVISOR, SELLER),
    "api_plan_trip": (ADMIN, SUPERVISOR), "api_trip_action": (ADMIN, SUPERVISOR, DRIVER),
    "api_trip_event": (ADMIN, SUPERVISOR, DRIVER), "api_route_stop": (ADMIN, SUPERVISOR, DRIVER),
    "api_payments": (ADMIN, SUPERVISOR, SELLER, DRIVER), "api_fuel_price": (ADMIN,),
    "api_order_action": (ADMIN, SUPERVISOR), "api_delete": (ADMIN, SUPERVISOR),
}


def role_policy(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if request.method != "GET":
            error = _require_role(request, *WRITE_ROLES[view.__name__])
            if error:
                return error
        return view(request, *args, **kwargs)
    return wrapped
