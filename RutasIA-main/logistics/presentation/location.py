import math
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from logistics.domain.exceptions import PlanningError


def parse_location(payload, prefix="", required=False):
    lat = payload.get(prefix + "latitude")
    lon = payload.get(prefix + "longitude")
    if lat is None and lon is None and not required:
        return None
    try:
        latitude, longitude = Decimal(str(lat)), Decimal(str(lon))
        if not latitude.is_finite() or not longitude.is_finite():
            raise ValueError
        if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
            raise ValueError
        accuracy = payload.get(prefix + "accuracy_m")
        accuracy = float(accuracy) if accuracy is not None else None
        if accuracy is not None and (not math.isfinite(accuracy) or accuracy < 0):
            raise ValueError
        stamp = payload.get(prefix + "captured_at")
        captured = parse_datetime(stamp) if stamp else None
        if stamp and (captured is None or timezone.is_naive(captured)):
            raise ValueError
        if captured and captured > timezone.now() + timedelta(minutes=5):
            raise ValueError
        return latitude, longitude, accuracy, captured
    except (ValueError, TypeError, InvalidOperation):
        raise PlanningError("Ubicacion invalida: revisa coordenadas, precision y fecha de captura.")
