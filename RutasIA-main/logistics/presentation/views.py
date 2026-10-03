from __future__ import annotations

from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db.models import Sum
from django.http import HttpRequest, HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_http_methods

from django.conf import settings as django_settings

from logistics.models import (
    Department,
    Driver,
    FuelPrice,
    Order,
    OrderItem,
    Payment,
    Product,
    RouteConnection,
    RouteStop,
    Store,
    Trip,
    UserProfile,
    Vehicle,
)
from logistics.domain.exceptions import PlanningError
from logistics.application.services import TripLifecycleService, TripPlanner
from logistics.presentation.serializers import (
    _as_float,
    _dashboard_payload,
    _error,
    _get_role,
    _ok,
    _parse_json,
    _require_role,
    _serialize_driver,
    _serialize_event,
    _serialize_order,
    _serialize_payment,
    _serialize_product,
    _serialize_route_stop,
    _serialize_store,
    _serialize_trip,
    _serialize_vehicle,
    _serialize_department,
)


@ensure_csrf_cookie
@login_required
@require_GET
def index(request: HttpRequest):
    return render(request, "logistics/index.html", {
        "ors_api_key": getattr(django_settings, "ORS_API_KEY", ""),
        "google_maps_api_key": getattr(django_settings, "GOOGLE_MAPS_API_KEY", ""),
    })


@login_required
@require_GET
def api_me(request: HttpRequest):
    user = request.user
    return _ok({
        "user": {
            "id": user.id,
            "username": user.username,
            "full_name": user.get_full_name(),
            "role": _get_role(request),
        }
    })


@login_required
@require_http_methods(["GET", "POST"])
def api_users(request: HttpRequest):
    perm_error = _require_role(request, UserProfile.Role.ADMIN)
    if perm_error:
        return perm_error

    if request.method == "GET":
        users = User.objects.select_related("profile").all().order_by("username")
        result = []
        for u in users:
            role = UserProfile.Role.OPERATOR
            try:
                role = u.profile.role
            except Exception:
                pass
            result.append({
                "id": u.id,
                "username": u.username,
                "full_name": u.get_full_name(),
                "email": u.email,
                "role": role,
                "is_active": u.is_active,
            })
        return _ok({"users": result})

    try:
        payload = _parse_json(request)
        username = str(payload["username"]).strip()
        password = str(payload["password"])
        role = payload.get("role", UserProfile.Role.OPERATOR)
        first_name = str(payload.get("first_name", "")).strip()
        last_name = str(payload.get("last_name", "")).strip()
        email = str(payload.get("email", "")).strip()

        if User.objects.filter(username=username).exists():
            return _error("El nombre de usuario ya existe.")
        if role not in [r[0] for r in UserProfile.Role.choices]:
            return _error("Rol inválido.")

        user = User.objects.create_user(
            username=username,
            password=password,
            first_name=first_name,
            last_name=last_name,
            email=email,
        )
        UserProfile.objects.create(user=user, role=role)
        return _ok({
            "user": {
                "id": user.id,
                "username": user.username,
                "full_name": user.get_full_name(),
                "email": user.email,
                "role": role,
                "is_active": user.is_active,
            }
        }, status=201)
    except KeyError as exc:
        return _error(f"Falta el campo requerido: {exc.args[0]}")
    except Exception as exc:
        return _error(str(exc))


@login_required
@require_GET
def api_dashboard(request: HttpRequest):
    date_from = request.GET.get("date_from")
    date_to = request.GET.get("date_to")
    return _ok({"dashboard": _dashboard_payload(date_from=date_from, date_to=date_to)})


@login_required
@require_http_methods(["GET", "POST"])
def api_departments(request: HttpRequest):
    if request.method == "GET":
        departments = Department.objects.all()
        return _ok({"departments": [_serialize_department(d) for d in departments]})

    perm_error = _require_role(request, UserProfile.Role.ADMIN, UserProfile.Role.SUPERVISOR)
    if perm_error:
        return perm_error

    try:
        payload = _parse_json(request)
        code = str(payload["code"]).strip().upper()
        name = str(payload["name"]).strip()
        latitude = payload.get("latitude")
        longitude = payload.get("longitude")

        if Department.objects.filter(code=code).exists():
            return _error("Ya existe un departamento con ese código.")
        if Department.objects.filter(name=name).exists():
            return _error("Ya existe un departamento con ese nombre.")

        department = Department.objects.create(
            code=code,
            name=name,
            latitude=Decimal(str(latitude)) if latitude is not None else None,
            longitude=Decimal(str(longitude)) if longitude is not None else None,
        )
        return _ok({"department": _serialize_department(department)}, status=201)
    except KeyError as exc:
        return _error(f"Falta el campo requerido: {exc.args[0]}")
    except Exception as exc:
        return _error(str(exc))


@login_required
@require_GET
def api_connections(request: HttpRequest):
    connections = (
        RouteConnection.objects.select_related("origin", "destination").all()
    )
    payload = [
        {
            "id": c.id,
            "origin_id": c.origin_id,
            "origin_name": c.origin.name,
            "destination_id": c.destination_id,
            "destination_name": c.destination.name,
            "distance_km": _as_float(c.distance_km),
            "is_bidirectional": c.is_bidirectional,
        }
        for c in connections
    ]
    return _ok({"connections": payload})


@login_required
@require_http_methods(["GET", "POST"])
def api_stores(request: HttpRequest):
    if request.method == "GET":
        stores = Store.objects.select_related("department").all()
        return _ok({"stores": [_serialize_store(store) for store in stores]})

    perm_error = _require_role(request, UserProfile.Role.ADMIN, UserProfile.Role.SUPERVISOR)
    if perm_error:
        return perm_error

    try:
        payload = _parse_json(request)
        department = Department.objects.get(pk=payload["department_id"])
        product_type = payload.get("product_type", Store.ProductType.WATER)
        if product_type not in [choice[0] for choice in Store.ProductType.choices]:
            return _error("Tipo de producto invalido.")

        store = Store.objects.create(
            name=str(payload["name"]).strip(),
            contact_name=str(payload.get("contact_name", "")).strip(),
            phone=str(payload.get("phone", "")).strip(),
            municipality=str(payload.get("municipality", "")).strip(),
            neighborhood=str(payload.get("neighborhood", "")).strip(),
            address=str(payload.get("address", "")).strip(),
            reference=str(payload.get("reference", "")).strip(),
            product_type=product_type,
            department=department,
            latitude=Decimal(str(payload["latitude"])),
            longitude=Decimal(str(payload["longitude"])),
            is_active=bool(payload.get("is_active", True)),
        )
        return _ok({"store": _serialize_store(store)}, status=201)
    except KeyError as exc:
        return _error(f"Falta el campo requerido: {exc.args[0]}")
    except Department.DoesNotExist:
        return _error("Zona/departamento invalido.")
    except Exception as exc:
        return _error(str(exc))


@login_required
@require_http_methods(["GET", "POST"])
def api_products(request: HttpRequest):
    if request.method == "GET":
        products = Product.objects.all()
        active_filter = request.GET.get("active")
        if active_filter in {"true", "1"}:
            products = products.filter(is_active=True)
        return _ok({"products": [_serialize_product(product) for product in products]})

    perm_error = _require_role(request, UserProfile.Role.ADMIN, UserProfile.Role.SUPERVISOR)
    if perm_error:
        return perm_error

    try:
        payload = _parse_json(request)
        product_type = payload.get("product_type", Product.Type.WATER)
        if product_type not in [choice[0] for choice in Product.Type.choices]:
            return _error("Tipo de producto invalido.")
        product = Product.objects.create(
            name=str(payload["name"]).strip(),
            product_type=product_type,
            presentation=str(payload.get("presentation", "")).strip(),
            unit_price=Decimal(str(payload["unit_price"])),
            unit_weight_kg=Decimal(str(payload.get("unit_weight_kg", "1.00"))),
            is_active=bool(payload.get("is_active", True)),
        )
        return _ok({"product": _serialize_product(product)}, status=201)
    except KeyError as exc:
        return _error(f"Falta el campo requerido: {exc.args[0]}")
    except Exception as exc:
        return _error(str(exc))


@login_required
@require_http_methods(["GET", "POST"])
def api_drivers(request: HttpRequest):
    if request.method == "GET":
        drivers = Driver.objects.all()
        return _ok({"drivers": [_serialize_driver(d) for d in drivers]})

    perm_error = _require_role(request, UserProfile.Role.ADMIN, UserProfile.Role.SUPERVISOR)
    if perm_error:
        return perm_error

    try:
        payload = _parse_json(request)
        driver = Driver.objects.create(
            name=str(payload["name"]).strip(),
            phone=str(payload.get("phone", "")).strip(),
            license_number=str(payload["license_number"]).strip(),
            is_active=bool(payload.get("is_active", True)),
        )
        return _ok({"driver": _serialize_driver(driver)}, status=201)
    except KeyError as exc:
        return _error(f"Falta el campo requerido: {exc.args[0]}")
    except Exception as exc:
        return _error(str(exc))


@login_required
@require_http_methods(["GET", "POST"])
def api_vehicles(request: HttpRequest):
    if request.method == "GET":
        vehicles = Vehicle.objects.select_related("current_department", "driver").all()
        return _ok({"vehicles": [_serialize_vehicle(v) for v in vehicles]})

    perm_error = _require_role(request, UserProfile.Role.ADMIN, UserProfile.Role.SUPERVISOR)
    if perm_error:
        return perm_error

    try:
        payload = _parse_json(request)
        current_department = None
        current_department_id = payload.get("current_department_id")
        if current_department_id:
            current_department = Department.objects.get(pk=current_department_id)

        driver = None
        driver_id = payload.get("driver_id")
        if driver_id:
            driver = Driver.objects.get(pk=driver_id)

        vehicle = Vehicle.objects.create(
            plate=str(payload["plate"]).strip().upper(),
            model=str(payload["model"]).strip(),
            capacity_kg=Decimal(str(payload["capacity_kg"])),
            fuel_efficiency_km_l=Decimal(str(payload["fuel_efficiency_km_l"])),
            cost_per_km=Decimal(str(payload["cost_per_km"])),
            is_active=bool(payload.get("is_active", True)),
            current_department=current_department,
            driver=driver,
        )
        return _ok({"vehicle": _serialize_vehicle(vehicle)}, status=201)
    except KeyError as exc:
        return _error(f"Falta el campo requerido: {exc.args[0]}")
    except Department.DoesNotExist:
        return _error("Departamento actual inválido.")
    except Driver.DoesNotExist:
        return _error("Conductor inválido.")
    except Exception as exc:
        return _error(str(exc))


@login_required
@require_http_methods(["GET", "POST"])
def api_orders(request: HttpRequest):
    if request.method == "GET":
        orders = (
            Order.objects.select_related("origin", "destination", "store")
            .prefetch_related("items__product", "payments")
            .all()
        )
        status_filter = request.GET.get("status")
        origin_filter = request.GET.get("origin_id")
        destination_filter = request.GET.get("destination_id")
        if status_filter:
            orders = orders.filter(status=status_filter)
        if origin_filter:
            orders = orders.filter(origin_id=origin_filter)
        if destination_filter:
            orders = orders.filter(destination_id=destination_filter)
        return _ok({"orders": [_serialize_order(o) for o in orders]})

    perm_error = _require_role(request, UserProfile.Role.ADMIN, UserProfile.Role.SUPERVISOR)
    if perm_error:
        return perm_error

    try:
        payload = _parse_json(request)
        origin = Department.objects.get(pk=payload["origin_id"])
        store = None
        store_id = payload.get("store_id")
        if store_id:
            store = Store.objects.select_related("department").get(pk=store_id, is_active=True)
            destination = store.department
        else:
            destination = Department.objects.get(pk=payload["destination_id"])
        if store is None and origin.id == destination.id:
            return _error("Origen y destino no pueden ser iguales.")

        items_payload = payload.get("items") or []
        order = Order.objects.create(
            origin=origin,
            destination=destination,
            store=store,
            weight_kg=Decimal(str(payload.get("weight_kg", "1.00"))),
            package_count=int(payload.get("package_count", 1)),
            priority=payload.get("priority", Order.Priority.NORMAL),
            status=Order.Status.PENDING,
        )
        if items_payload:
            total_weight = Decimal("0.00")
            total_packages = 0
            for item_payload in items_payload:
                product = Product.objects.get(pk=item_payload["product_id"], is_active=True)
                quantity = int(item_payload.get("quantity", 1))
                unit_price = Decimal(str(item_payload.get("unit_price", product.unit_price)))
                OrderItem.objects.create(
                    order=order,
                    product=product,
                    quantity=quantity,
                    unit_price=unit_price,
                )
                total_weight += Decimal(quantity) * Decimal(product.unit_weight_kg)
                total_packages += quantity
            order.weight_kg = total_weight
            order.package_count = total_packages or order.package_count
            order.save(update_fields=["weight_kg", "package_count", "updated_at"])
        return _ok({"order": _serialize_order(order)}, status=201)
    except KeyError as exc:
        return _error(f"Falta el campo requerido: {exc.args[0]}")
    except Department.DoesNotExist:
        return _error("Origen o destino inválido.")
    except Store.DoesNotExist:
        return _error("Tienda/cliente invalido.")
    except Product.DoesNotExist:
        return _error("Producto invalido.")
    except Exception as exc:
        return _error(str(exc))


@login_required
@require_http_methods(["GET"])
def api_trips(request: HttpRequest):
    trips = (
        Trip.objects.select_related("vehicle", "driver", "origin", "destination")
        .prefetch_related("orders__origin", "orders__destination", "orders__store", "orders__items__product", "orders__payments", "stops__order", "stops__store", "events")
        .all()
    )
    status_filter = request.GET.get("status")
    vehicle_filter = request.GET.get("vehicle_id")
    date_from = request.GET.get("date_from")
    date_to = request.GET.get("date_to")
    if status_filter:
        trips = trips.filter(status=status_filter)
    if vehicle_filter:
        trips = trips.filter(vehicle_id=vehicle_filter)
    if date_from:
        trips = trips.filter(created_at__date__gte=date_from)
    if date_to:
        trips = trips.filter(created_at__date__lte=date_to)
    return _ok({"trips": [_serialize_trip(trip) for trip in trips]})


@login_required
@require_http_methods(["POST"])
def api_plan_trip(request: HttpRequest):
    perm_error = _require_role(request, UserProfile.Role.ADMIN, UserProfile.Role.SUPERVISOR)
    if perm_error:
        return perm_error

    try:
        payload = _parse_json(request)
        vehicle = Vehicle.objects.get(pk=payload["vehicle_id"])
        order_ids = payload.get("order_ids", [])
        if not isinstance(order_ids, list):
            return _error("order_ids debe ser una lista de IDs.")

        driver = None
        driver_id = payload.get("driver_id")
        if driver_id:
            try:
                driver = Driver.objects.get(pk=driver_id, is_active=True)
            except Driver.DoesNotExist:
                return _error("Conductor inválido o inactivo.")

        orders = Order.objects.select_related("origin", "destination", "store").filter(id__in=order_ids)
        if orders.count() != len(set(order_ids)):
            return _error("Uno o más pedidos no existen.")

        algorithm = payload.get("algorithm", "dijkstra")
        if algorithm not in ("dijkstra", "astar"):
            return _error("Algoritmo inválido. Use 'dijkstra' o 'astar'.")

        trip = TripPlanner.plan_trip(vehicle=vehicle, orders=orders, driver=driver, algorithm=algorithm)
        trip = (
            Trip.objects.select_related("vehicle", "driver", "origin", "destination")
            .prefetch_related("orders__origin", "orders__destination", "orders__store", "orders__items__product", "orders__payments", "stops__order", "stops__store", "events")
            .get(pk=trip.pk)
        )
        return _ok({"trip": _serialize_trip(trip)}, status=201)
    except Vehicle.DoesNotExist:
        return _error("Vehículo inválido.")
    except PlanningError as exc:
        return _error(str(exc))
    except KeyError as exc:
        return _error(f"Falta el campo requerido: {exc.args[0]}")
    except Exception as exc:
        return _error(str(exc))


@login_required
@require_http_methods(["POST"])
def api_trip_action(request: HttpRequest, trip_id: int):
    trip = get_object_or_404(
        Trip.objects.select_related("vehicle", "driver", "origin", "destination").prefetch_related(
            "orders__origin", "orders__destination", "orders__store", "orders__items__product", "orders__payments", "stops__order", "stops__store", "events"
        ),
        pk=trip_id,
    )
    perm_error = _require_role(request, UserProfile.Role.ADMIN, UserProfile.Role.SUPERVISOR)
    if perm_error:
        return perm_error

    try:
        payload = _parse_json(request)
        action = payload.get("action")
        if action == "start":
            TripLifecycleService.start_trip(trip)
        elif action == "complete":
            TripLifecycleService.complete_trip(trip)
        elif action == "cancel":
            TripLifecycleService.cancel_trip(trip)
        else:
            return _error("Acción inválida. Usa: start, complete o cancel.")

        trip.refresh_from_db()
        trip = (
            Trip.objects.select_related("vehicle", "driver", "origin", "destination")
            .prefetch_related("orders__origin", "orders__destination", "orders__store", "orders__items__product", "orders__payments", "stops__order", "stops__store", "events")
            .get(pk=trip.pk)
        )
        return _ok({"trip": _serialize_trip(trip)})
    except PlanningError as exc:
        return _error(str(exc))


@login_required
@require_http_methods(["POST"])
def api_trip_event(request: HttpRequest, trip_id: int):
    trip = get_object_or_404(Trip, pk=trip_id)
    try:
        payload = _parse_json(request)
        note = str(payload.get("note", ""))
        event = TripLifecycleService.add_event(trip, note)
        return _ok({"event": _serialize_event(event)}, status=201)
    except PlanningError as exc:
        return _error(str(exc))


@login_required
@require_http_methods(["POST"])
def api_route_stop(request: HttpRequest, trip_id: int, stop_id: int):
    stop = get_object_or_404(RouteStop.objects.select_related("trip", "order", "store"), pk=stop_id, trip_id=trip_id)
    try:
        payload = _parse_json(request)
        status = payload.get("status", RouteStop.Status.DELIVERED)
        if status not in [choice[0] for choice in RouteStop.Status.choices]:
            return _error("Estado de parada invalido.")
        stop.status = status
        stop.observation = str(payload.get("observation", stop.observation)).strip()
        stop.delivered_at = timezone.now() if status == RouteStop.Status.DELIVERED else None
        stop.save(update_fields=["status", "observation", "delivered_at", "updated_at"])
        if stop.order:
            if status == RouteStop.Status.DELIVERED:
                stop.order.status = Order.Status.DELIVERED
            elif status == RouteStop.Status.NOT_DELIVERED:
                stop.order.status = Order.Status.PENDING
            stop.order.save(update_fields=["status", "updated_at"])
        return _ok({"stop": _serialize_route_stop(stop)})
    except PlanningError as exc:
        return _error(str(exc))
    except Exception as exc:
        return _error(str(exc))


@login_required
@require_http_methods(["GET", "POST"])
def api_payments(request: HttpRequest):
    if request.method == "GET":
        payments = Payment.objects.select_related("store", "order", "trip").all()
        store_id = request.GET.get("store_id")
        if store_id:
            payments = payments.filter(store_id=store_id)
        return _ok({"payments": [_serialize_payment(payment) for payment in payments]})

    try:
        payload = _parse_json(request)
        store = Store.objects.get(pk=payload["store_id"], is_active=True)
        order = None
        order_id = payload.get("order_id")
        if order_id:
            order = Order.objects.get(pk=order_id, store=store)
        trip = None
        trip_id = payload.get("trip_id")
        if trip_id:
            trip = Trip.objects.get(pk=trip_id)
        payment_uuid = payload.get("uuid")
        if payment_uuid:
            existing = Payment.objects.filter(uuid=payment_uuid).select_related("store", "order", "trip").first()
            if existing:
                return _ok({"payment": _serialize_payment(existing), "duplicate": True})
        payment_data = {
            "store": store,
            "order": order,
            "trip": trip,
            "amount": Decimal(str(payload["amount"])),
            "payment_type": payload.get("payment_type", Payment.PaymentType.PARTIAL),
            "method": payload.get("method", Payment.Method.CASH),
            "sync_status": payload.get("sync_status", Payment.SyncStatus.SYNCED),
            "note": str(payload.get("note", "")).strip(),
        }
        if payment_uuid:
            payment_data["uuid"] = payment_uuid
        payment = Payment.objects.create(**payment_data)
        return _ok({"payment": _serialize_payment(payment)}, status=201)
    except KeyError as exc:
        return _error(f"Falta el campo requerido: {exc.args[0]}")
    except Store.DoesNotExist:
        return _error("Tienda/cliente invalido.")
    except Order.DoesNotExist:
        return _error("Pedido invalido para esta tienda.")
    except Trip.DoesNotExist:
        return _error("Ruta invalida.")
    except Exception as exc:
        return _error(str(exc))


@login_required
@require_http_methods(["GET"])
def api_balances(request: HttpRequest):
    orders = Order.objects.select_related("store").prefetch_related("items", "payments").filter(store__isnull=False)
    balances: dict[int, dict] = {}
    for order in orders:
        store = order.store
        if store.id not in balances:
            balances[store.id] = {
                "store_id": store.id,
                "store_name": store.name,
                "municipality": store.municipality,
                "neighborhood": store.neighborhood,
                "sales_total": Decimal("0.00"),
                "paid_total": Decimal("0.00"),
                "balance_due": Decimal("0.00"),
            }
        balances[store.id]["sales_total"] += order.total_amount
        balances[store.id]["paid_total"] += order.paid_amount
        balances[store.id]["balance_due"] += order.balance_due

    payload = []
    for row in balances.values():
        payload.append({
            **row,
            "sales_total": _as_float(row["sales_total"]),
            "paid_total": _as_float(row["paid_total"]),
            "balance_due": _as_float(row["balance_due"]),
        })
    payload.sort(key=lambda item: item["balance_due"], reverse=True)
    return _ok({"balances": payload})


@login_required
@require_http_methods(["GET"])
def api_reports(request: HttpRequest):
    date_from = request.GET.get("date_from")
    date_to = request.GET.get("date_to")
    orders = Order.objects.prefetch_related("items", "payments")
    trips = Trip.objects.all()
    payments = Payment.objects.all()
    if date_from:
        orders = orders.filter(created_at__date__gte=date_from)
        trips = trips.filter(created_at__date__gte=date_from)
        payments = payments.filter(created_at__date__gte=date_from)
    if date_to:
        orders = orders.filter(created_at__date__lte=date_to)
        trips = trips.filter(created_at__date__lte=date_to)
        payments = payments.filter(created_at__date__lte=date_to)

    sales_total = sum((order.total_amount for order in orders), Decimal("0.00"))
    paid_total = payments.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
    delivered_orders = orders.filter(status=Order.Status.DELIVERED).count()
    pending_orders = orders.filter(status=Order.Status.PENDING).count()
    return _ok({
        "report": {
            "sales_total": _as_float(sales_total),
            "paid_total": _as_float(paid_total),
            "balance_due": _as_float(max(sales_total - paid_total, Decimal("0.00"))),
            "orders": orders.count(),
            "delivered_orders": delivered_orders,
            "pending_orders": pending_orders,
            "trips": trips.count(),
            "distance_km": _as_float(trips.aggregate(total=Sum("total_distance_km"))["total"]),
            "fuel_cost_gtq": _as_float(trips.aggregate(total=Sum("estimated_fuel_cost_gtq"))["total"]),
        }
    })


@login_required
@require_http_methods(["GET", "POST"])
def api_fuel_price(request: HttpRequest):
    fp = FuelPrice.current()

    if request.method == "GET":
        return _ok({
            "fuel_price": {
                "regular_gtq_gal": _as_float(fp.regular_gtq_gal),
                "super_gtq_gal": _as_float(fp.super_gtq_gal),
                "diesel_gtq_gal": _as_float(fp.diesel_gtq_gal),
                "source": fp.source,
                "updated_at": timezone.localtime(fp.updated_at).isoformat(),
            }
        })

    perm_error = _require_role(request, UserProfile.Role.ADMIN)
    if perm_error:
        return perm_error

    try:
        payload = _parse_json(request)
        fp.regular_gtq_gal = Decimal(str(payload["regular_gtq_gal"]))
        fp.super_gtq_gal = Decimal(str(payload["super_gtq_gal"]))
        fp.diesel_gtq_gal = Decimal(str(payload["diesel_gtq_gal"]))
        fp.source = str(payload.get("source", "Manual"))
        fp.save()
        return _ok({
            "fuel_price": {
                "regular_gtq_gal": _as_float(fp.regular_gtq_gal),
                "super_gtq_gal": _as_float(fp.super_gtq_gal),
                "diesel_gtq_gal": _as_float(fp.diesel_gtq_gal),
                "source": fp.source,
                "updated_at": timezone.localtime(fp.updated_at).isoformat(),
            }
        })
    except (KeyError, ValueError) as exc:
        return _error(f"Datos inválidos: {exc}")


def method_not_allowed(_: HttpRequest):
    return HttpResponseNotAllowed(["GET", "POST"])
