from decimal import Decimal, InvalidOperation

from logistics.domain.exceptions import PlanningError


def decimal_field(value, label, allow_zero=False):
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number < 0 or (number == 0 and not allow_zero):
            raise ValueError
        if number != number.quantize(Decimal("0.01")):
            raise ValueError
        return number
    except (ValueError, InvalidOperation):
        raise PlanningError(f"{label}: utiliza un numero {'no negativo' if allow_zero else 'positivo'} con hasta dos decimales.")


def required_text(value, label):
    result = str(value).strip() if value is not None else ""
    if not result:
        raise PlanningError(f"{label} es obligatorio.")
    return result
