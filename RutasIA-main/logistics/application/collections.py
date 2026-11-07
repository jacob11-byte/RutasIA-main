"""Collection rules shared by online requests and offline replays."""
import uuid
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from logistics.domain.exceptions import PlanningError
from logistics.models import Driver, Order, Payment, PaymentAllocation, Store, Trip


def operation_time(value):
    if not value:
        return timezone.now()
    try:
        result = parse_datetime(value)
        if result is None or timezone.is_naive(result) or result > timezone.now() + timedelta(minutes=5):
            raise ValueError
        return result
    except (TypeError, ValueError):
        raise PlanningError("La fecha de la operacion no es valida.")


@transaction.atomic
def record_collection(payload, user):
    try:
        store = Store.objects.select_for_update().get(pk=payload["store_id"], is_active=True)
        amount = Decimal(str(payload["amount"]))
        if not amount.is_finite() or amount != amount.quantize(Decimal("0.01")) or amount < 0:
            raise PlanningError("El monto debe ser valido y tener hasta dos decimales.")
        kind = payload.get("payment_type", Payment.PaymentType.PARTIAL)
        method = payload.get("method", Payment.Method.CASH)
        if kind not in Payment.PaymentType.values or method not in Payment.Method.values:
            raise PlanningError("Tipo o metodo de pago invalido.")
        key = uuid.UUID(str(payload["uuid"])) if payload.get("uuid") else uuid.uuid4()
        order = Order.objects.get(pk=payload["order_id"], store=store) if payload.get("order_id") else None
        trip = Trip.objects.select_related("driver").get(pk=payload["trip_id"]) if payload.get("trip_id") else None
        if trip and not trip.orders.filter(store=store, **({"pk": order.pk} if order else {})).exists():
            raise PlanningError("La ruta no corresponde al cliente o pedido seleccionado.")
        existing = Payment.objects.filter(uuid=key).first()
        if existing:
            if (existing.store_id, existing.order_id, existing.amount, existing.payment_type, existing.method) != (store.pk, order.pk if order else None, amount, kind, method):
                raise PlanningError("El UUID pertenece a un cobro diferente.")
            return existing, True
        orders = list(Order.objects.filter(store=store).exclude(status=Order.Status.CANCELED)
                      .prefetch_related("items", "payments", "payment_allocations").order_by("requested_for", "id"))
        balance = order.balance_due if order else sum((item.balance_due for item in orders), Decimal("0"))
        if order and order.status == Order.Status.CANCELED:
            raise PlanningError("No se puede cobrar un pedido cancelado.")
        if kind == Payment.PaymentType.CREDIT:
            if not order or amount != 0 or balance <= 0:
                raise PlanningError("El credito requiere un pedido con saldo y monto recibido de Q 0.00.")
        else:
            if amount <= 0 or amount > balance:
                raise PlanningError("El monto recibido debe ser positivo y no superar el saldo pendiente.")
            if kind == Payment.PaymentType.FULL and amount != balance:
                raise PlanningError("El pago completo debe coincidir con el saldo pendiente.")
        driver = trip.driver if trip else None
        if payload.get("driver_id"):
            driver = Driver.objects.get(pk=payload["driver_id"], is_active=True)
            if trip and trip.driver_id and trip.driver_id != driver.pk:
                raise PlanningError("El repartidor no corresponde a la ruta seleccionada.")
        if driver is None and order:
            last_trip = order.trips.exclude(status=Trip.Status.CANCELED).select_related("driver").order_by("-created_at").first()
            if last_trip:
                driver, trip = last_trip.driver, trip or last_trip
        note = str(payload.get("note", "")).strip()
        if len(note) > 240:
            raise PlanningError("La nota del cobro admite hasta 240 caracteres.")
        payment = Payment.objects.create(
            uuid=key, store=store, order=order, trip=trip, driver=driver, recorded_by=user,
            amount=amount, payment_type=kind, method=method, sync_status=Payment.SyncStatus.SYNCED,
            occurred_at=operation_time(payload.get("occurred_at")), note=note,
        )
        # A collection against the whole customer settles oldest debts first.
        if order is None and amount > 0:
            remaining = amount
            for item in orders:
                applied = min(remaining, item.balance_due)
                if applied > 0:
                    PaymentAllocation.objects.create(payment=payment, order=item, amount=applied)
                    remaining -= applied
                if remaining == 0:
                    break
        return payment, False
    except (Store.DoesNotExist, Order.DoesNotExist, Trip.DoesNotExist, Driver.DoesNotExist):
        raise PlanningError("Cliente, pedido, ruta o repartidor invalido.")
    except (InvalidOperation, ValueError, TypeError):
        raise PlanningError("El monto o identificador del cobro no es valido.")
