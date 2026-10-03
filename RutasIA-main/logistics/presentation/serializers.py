from __future__ import annotations

import json
from decimal import Decimal

from django.http import HttpRequest, JsonResponse
from django.utils import timezone

from logistics.models import (
    Department,
    Driver,
    Order,
    OrderItem,
    Payment,
    Product,
    RouteStop,
    Store,
    Trip,
    TripEvent,
    UserProfile,
    Vehicle,
)
from logistics.domain.exceptions import PlanningError


def _as_float(value: Decimal | None) -> float:
    return float(value or 0)


def _parse_json(request: HttpRequest) -> dict:
    if not request.body:
        return {}
    try:
        return json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise PlanningError("JSON inválido en la solicitud.")


def _ok(payload: dict, status: int = 200) -> JsonResponse:
    return JsonResponse({"ok": True, **payload}, status=status)


def _error(message: str, status: int = 400) -> JsonResponse:
    return JsonResponse({"ok": False, "error": message}, status=status)


def _get_role(request: HttpRequest) -> str:
    try:
        return request.user.profile.role
    except Exception:
        return UserProfile.Role.OPERATOR


def _require_role(request: HttpRequest, *allowed_roles: str) -> JsonResponse | None:
    if _get_role(request) not in allowed_roles:
        return _error("No tienes permisos para esta acción.", 403)
    return None


def _serialize_department(department: Department) -> dict:
    return {
        "id": department.id,
        "code": department.code,
        "name": department.name,
        "latitude": float(department.latitude) if department.latitude else None,
        "longitude": float(department.longitude) if department.longitude else None,
    }


def _serialize_driver(driver: Driver) -> dict:
    return {
        "id": driver.id,
        "name": driver.name,
        "phone": driver.phone,
        "license_number": driver.license_number,
        "is_active": driver.is_active,
    }


def _serialize_vehicle(vehicle: Vehicle) -> dict:
    return {
        "id": vehicle.id,
        "plate": vehicle.plate,
        "model": vehicle.model,
        "capacity_kg": _as_float(vehicle.capacity_kg),
        "fuel_efficiency_km_l": _as_float(vehicle.fuel_efficiency_km_l),
        "cost_per_km": _as_float(vehicle.cost_per_km),
        "is_active": vehicle.is_active,
        "current_department_id": vehicle.current_department_id,
        "current_department_name": vehicle.current_department.name if vehicle.current_department else None,
        "driver_id": vehicle.driver_id,
        "driver_name": vehicle.driver.name if vehicle.driver else None,
    }


def _serialize_store(store: Store) -> dict:
    balance_due = getattr(store, "balance_due_value", None)
    return {
        "id": store.id,
        "name": store.name,
        "contact_name": store.contact_name,
        "phone": store.phone,
        "municipality": store.municipality,
        "neighborhood": store.neighborhood,
        "address": store.address,
        "reference": store.reference,
        "product_type": store.product_type,
        "department_id": store.department_id,
        "department_name": store.department.name,
        "latitude": float(store.latitude),
        "longitude": float(store.longitude),
        "is_active": store.is_active,
        "balance_due": _as_float(balance_due) if balance_due is not None else 0,
    }


def _serialize_product(product: Product) -> dict:
    return {
        "id": product.id,
        "name": product.name,
        "product_type": product.product_type,
        "presentation": product.presentation,
        "unit_price": _as_float(product.unit_price),
        "unit_weight_kg": _as_float(product.unit_weight_kg),
        "is_active": product.is_active,
    }


def _serialize_order_item(item: OrderItem) -> dict:
    return {
        "id": item.id,
        "product_id": item.product_id,
        "product_name": item.product.name,
        "presentation": item.product.presentation,
        "quantity": item.quantity,
        "unit_price": _as_float(item.unit_price),
        "subtotal": _as_float(item.subtotal),
    }


def _serialize_order(order: Order) -> dict:
    total_amount = order.total_amount
    paid_amount = order.paid_amount
    return {
        "id": order.id,
        "code": order.code,
        "origin_id": order.origin_id,
        "origin_name": order.origin.name,
        "destination_id": order.destination_id,
        "destination_name": order.destination.name,
        "store_id": order.store_id,
        "store_name": order.store.name if order.store else None,
        "store_latitude": float(order.store.latitude) if order.store else None,
        "store_longitude": float(order.store.longitude) if order.store else None,
        "store_address": order.store.address if order.store else "",
        "store_reference": order.store.reference if order.store else "",
        "weight_kg": _as_float(order.weight_kg),
        "package_count": order.package_count,
        "priority": order.priority,
        "status": order.status,
        "requested_for": order.requested_for.isoformat(),
        "items": [_serialize_order_item(item) for item in order.items.all()],
        "total_amount": _as_float(total_amount),
        "paid_amount": _as_float(paid_amount),
        "balance_due": _as_float(max(total_amount - paid_amount, Decimal("0.00"))),
    }


def _serialize_payment(payment: Payment) -> dict:
    return {
        "id": payment.id,
        "uuid": str(payment.uuid),
        "store_id": payment.store_id,
        "store_name": payment.store.name,
        "order_id": payment.order_id,
        "order_code": payment.order.code if payment.order else None,
        "trip_id": payment.trip_id,
        "trip_code": payment.trip.code if payment.trip else None,
        "amount": _as_float(payment.amount),
        "payment_type": payment.payment_type,
        "method": payment.method,
        "sync_status": payment.sync_status,
        "note": payment.note,
        "created_at": timezone.localtime(payment.created_at).isoformat(),
    }


def _serialize_route_stop(stop: RouteStop) -> dict:
    return {
        "id": stop.id,
        "sequence": stop.sequence,
        "status": stop.status,
        "observation": stop.observation,
        "order_id": stop.order_id,
        "order_code": stop.order.code if stop.order else None,
        "store_id": stop.store_id,
        "store_name": stop.store.name if stop.store else None,
        "latitude": float(stop.latitude) if stop.latitude is not None else None,
        "longitude": float(stop.longitude) if stop.longitude is not None else None,
        "delivered_at": stop.delivered_at.isoformat() if stop.delivered_at else None,
    }


def _serialize_event(event: TripEvent) -> dict:
    return {
        "id": event.id,
        "note": event.note,
        "created_at": timezone.localtime(event.created_at).isoformat(),
    }


def _serialize_trip(trip: Trip) -> dict:
    return {
        "id": trip.id,
        "code": trip.code,
        "vehicle_id": trip.vehicle_id,
        "vehicle_plate": trip.vehicle.plate,
        "driver_id": trip.driver_id,
        "driver_name": trip.driver.name if trip.driver else None,
        "origin_name": trip.origin.name,
        "destination_name": trip.destination.name,
        "route_nodes": trip.route_nodes,
        "total_distance_km": _as_float(trip.total_distance_km),
        "estimated_fuel_gallons": _as_float(trip.estimated_fuel_gallons),
        "fuel_price_gtq_gal": _as_float(trip.fuel_price_gtq_gal) if trip.fuel_price_gtq_gal else None,
        "estimated_fuel_cost_gtq": _as_float(trip.estimated_fuel_cost_gtq) if trip.estimated_fuel_cost_gtq else None,
        "estimated_cost": _as_float(trip.estimated_cost),
        "status": trip.status,
        "started_at": trip.started_at.isoformat() if trip.started_at else None,
        "completed_at": trip.completed_at.isoformat() if trip.completed_at else None,
        "orders": [_serialize_order(order) for order in trip.orders.all().order_by("-created_at")],
        "stops": [_serialize_route_stop(stop) for stop in trip.stops.all()],
        "events": [_serialize_event(event) for event in trip.events.all()],
    }


def _dashboard_payload(date_from=None, date_to=None) -> dict:
    from django.db.models import Count, Sum
    from django.utils import timezone as tz
    from datetime import timedelta

    trips = Trip.objects.all()
    if date_from:
        trips = trips.filter(created_at__date__gte=date_from)
    if date_to:
        trips = trips.filter(created_at__date__lte=date_to)

    aggregates = trips.aggregate(
        total_trips=Count("id"),
        total_cost=Sum("estimated_cost"),
        total_distance=Sum("total_distance_km"),
    )

    status_distribution = list(
        trips.values("status").annotate(total=Count("id")).order_by("status")
    )
    vehicle_activity = list(
        Vehicle.objects.annotate(total_trips=Count("trips"))
        .order_by("-total_trips", "plate")
        .values("plate", "total_trips")[:6]
    )

    today = tz.localdate()
    timeline = []
    for delta in range(6, -1, -1):
        day = today - timedelta(days=delta)
        timeline.append(
            {
                "date": day.isoformat(),
                "trips": trips.filter(created_at__date=day).count(),
            }
        )

    from logistics.models import Order as _Order
    return {
        "summary": {
            "total_trips": aggregates["total_trips"] or 0,
            "active_trips": trips.filter(status__in=[Trip.Status.PLANNED, Trip.Status.IN_PROGRESS]).count(),
            "pending_orders": _Order.objects.filter(status=_Order.Status.PENDING).count(),
            "delivered_orders": _Order.objects.filter(status=_Order.Status.DELIVERED).count(),
            "total_cost": _as_float(aggregates["total_cost"]),
            "total_distance_km": _as_float(aggregates["total_distance"]),
        },
        "status_distribution": status_distribution,
        "vehicle_activity": vehicle_activity,
        "timeline": timeline,
    }
