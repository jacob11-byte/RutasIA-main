from __future__ import annotations

from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from django.db.models import Q, Sum
from django.http import HttpRequest, HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render
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
    TripEvent,
    UserProfile,
    Vehicle,
)
from logistics.forms import EmployeeSignupForm
from logistics.presentation.idempotency import idempotent
from logistics.presentation.permissions import role_policy
from logistics.presentation.validation import decimal_field, required_text
from logistics.application.collections import record_collection, operation_time
from logistics.presentation.location import parse_location
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


@require_http_methods(["GET", "POST"])
def signup(request: HttpRequest):
    if request.user.is_authenticated:
        return redirect("index")
    form = EmployeeSignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            user = form.save(commit=False)
            user.is_active = False
            user.save()
            role = form.cleaned_data["role"]
            UserProfile.objects.create(user=user, role=role)
            if role == UserProfile.Role.DRIVER:
                Driver.objects.create(
                    user=user,
                    name=user.get_full_name() or user.username,
                    phone=form.cleaned_data.get("phone", "").strip(),
                    license_number=form.cleaned_data["license_number"].strip(),
                    is_active=False,
                )
        messages.success(request, "Cuenta creada. Un administrador debe aprobarla antes de que puedas ingresar.")
        return redirect("login")
    return render(request, "registration/signup.html", {"form": form})


def _assigned_driver(request: HttpRequest) -> Driver | None:
    try:
        return request.user.driver_profile
    except Driver.DoesNotExist:
        return None


def _require_assigned_trip(request: HttpRequest, trip: Trip):
    if _get_role(request) != UserProfile.Role.DRIVER:
        return None
    driver = _assigned_driver(request)
    if driver is None or trip.driver_id != driver.pk:
        return _error("Esta ruta no esta asignada a tu cuenta de repartidor.", 403)
    return None


@ensure_csrf_cookie
@login_required
@require_GET
def index(request: HttpRequest):
    response = render(request, "logistics/index.html", {
        "ors_api_key": getattr(django_settings, "ORS_API_KEY", ""),
        "google_maps_api_key": getattr(django_settings, "GOOGLE_MAPS_API_KEY", ""),
    })
    response["X-Flamia-User-ID"] = str(request.user.pk)
    response["Cache-Control"] = "no-store"
    return response


@login_required
@require_GET
@ensure_csrf_cookie
def api_me(request: HttpRequest):
    user = request.user
    driver = _assigned_driver(request)
    return _ok({
        "user": {
            "id": user.id,
            "username": user.username,
            "full_name": user.get_full_name(),
            "role": _get_role(request),
            "driver_id": driver.pk if driver else None,
        }
    })


@login_required
@require_http_methods(["GET", "POST"])
@role_policy
@idempotent
def api_users(request: HttpRequest):
    perm_error = _require_role(request, UserProfile.Role.ADMIN)
    if perm_error:
        return perm_error

    if request.method == "GET":
        users = User.objects.select_related("profile").all().order_by("username")
        result = []
        for u in users:
            role = UserProfile.Role.SELLER
            try:
                role = u.profile.role
            except Exception:
                pass
            if u.is_superuser:
                role = UserProfile.Role.ADMIN
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
        username = required_text(payload["username"], "Usuario")
        password = str(payload["password"])
        role = payload.get("role", UserProfile.Role.SELLER)
        first_name = str(payload.get("first_name", "")).strip()
        last_name = str(payload.get("last_name", "")).strip()
        email = str(payload.get("email", "")).strip()

        if User.objects.filter(username=username).exists():
            return _error("El nombre de usuario ya existe.")
        if role not in [r[0] for r in UserProfile.Role.choices]:
            return _error("Rol inválido.")

        validate_password(password, User(username=username, first_name=first_name, last_name=last_name, email=email))
        user = User.objects.create_user(
            username=username,
            password=password,
            first_name=first_name,
            last_name=last_name,
            email=email,
        )
        UserProfile.objects.create(user=user, role=role)
        if role == UserProfile.Role.DRIVER:
            license_number = required_text(payload.get("license_number", ""), "Licencia del repartidor")
            Driver.objects.create(
                user=user,
                name=user.get_full_name() or user.username,
                phone=str(payload.get("phone", "")).strip(),
                license_number=license_number,
                is_active=user.is_active,
            )
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
@require_http_methods(["POST"])
@role_policy
@idempotent
def api_user_detail(request: HttpRequest, user_id: int):
    try:
        payload = _parse_json(request)
        user = get_object_or_404(User.objects.select_for_update(), pk=user_id)
        role = payload.get("role")
        active = payload.get("is_active", user.is_active)
        if role not in UserProfile.Role.values or not isinstance(active, bool):
            return _error("Rol o estado de usuario invalido.")
        if request.user.pk == user.pk and (role != UserProfile.Role.ADMIN or not active):
            return _error("No puedes retirar tu propio acceso administrativo.")
        if user.is_superuser and (role != UserProfile.Role.ADMIN or not active):
            return _error("La cuenta superadministradora debe conservar su acceso.")
        if role == UserProfile.Role.DRIVER and not Driver.objects.filter(user=user).exists():
            return _error("Para asignar el rol Repartidor, crea la cuenta desde el registro con su licencia.")
        UserProfile.objects.update_or_create(user=user, defaults={"role": role})
        user.is_active = active
        user.save(update_fields=["is_active"])
        Driver.objects.filter(user=user).update(is_active=active)
        return _ok({"user": {"id": user.pk, "username": user.username, "role": role, "is_active": active}})
    except (KeyError, PlanningError) as exc:
        return _error(str(exc))


@login_required
@require_GET
def api_dashboard(request: HttpRequest):
    date_from = request.GET.get("date_from")
    date_to = request.GET.get("date_to")
    driver_user_id = request.user.pk if _get_role(request) == UserProfile.Role.DRIVER else None
    return _ok({"dashboard": _dashboard_payload(date_from=date_from, date_to=date_to, driver_user_id=driver_user_id)})


@login_required
@require_http_methods(["GET", "POST"])
@role_policy
@idempotent
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
@role_policy
@idempotent
def api_stores(request: HttpRequest):
    if request.method == "GET":
        stores = Store.objects.select_related("department", "created_by").all()
        if _get_role(request) == UserProfile.Role.DRIVER:
            stores = stores.filter(orders__trips__driver__user=request.user).distinct()
        return _ok({"stores": [_serialize_store(store) for store in stores]})

    perm_error = _require_role(request, UserProfile.Role.ADMIN, UserProfile.Role.SUPERVISOR, UserProfile.Role.SELLER)
    if perm_error:
        return perm_error

    try:
        payload = _parse_json(request)
        department = Department.objects.get(pk=payload["department_id"])
        product_type = payload.get("product_type", Store.ProductType.WATER)
        if product_type not in [choice[0] for choice in Store.ProductType.choices]:
            return _error("Tipo de producto invalido.")
        visit_frequency = payload.get("visit_frequency", Store.VisitFrequency.ON_DEMAND)
        if visit_frequency not in Store.VisitFrequency.values:
            return _error("Frecuencia de visita invalida.")

        latitude, longitude, accuracy, captured = parse_location(payload, required=True)
        store = Store.objects.create(
            name=required_text(payload["name"], "Nombre"),
            contact_name=str(payload.get("contact_name", "")).strip(),
            phone=str(payload.get("phone", "")).strip(),
            municipality=str(payload.get("municipality", "")).strip(),
            neighborhood=str(payload.get("neighborhood", "")).strip(),
            address=str(payload.get("address", "")).strip(),
            reference=str(payload.get("reference", "")).strip(),
            product_type=product_type,
            visit_frequency=visit_frequency,
            department=department,
            latitude=latitude,
            longitude=longitude,
            location_accuracy_m=accuracy,
            location_captured_at=captured,
            created_by=request.user,
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
@require_http_methods(["POST"])
@role_policy
@idempotent
def api_store_detail(request: HttpRequest, store_id: int):
    store = get_object_or_404(Store.objects.select_for_update().select_related("department", "created_by"), pk=store_id)
    try:
        payload = _parse_json(request)
        if "department_id" in payload:
            store.department = Department.objects.get(pk=payload["department_id"])
        product_type = payload.get("product_type", store.product_type)
        visit_frequency = payload.get("visit_frequency", store.visit_frequency)
        if product_type not in Store.ProductType.values or visit_frequency not in Store.VisitFrequency.values:
            return _error("Tipo de producto o frecuencia invalida.")
        location = parse_location(payload)
        if location:
            store.latitude, store.longitude, store.location_accuracy_m, store.location_captured_at = location
        for field in ("name", "contact_name", "phone", "municipality", "neighborhood", "address", "reference"):
            if field in payload:
                value = str(payload[field]).strip()
                if field == "name" and not value:
                    return _error("El nombre de la tienda es obligatorio.")
                setattr(store, field, value)
        store.product_type = product_type
        store.visit_frequency = visit_frequency
        if "is_active" in payload:
            store.is_active = bool(payload["is_active"])
        store.save()
        return _ok({"store": _serialize_store(store)})
    except Department.DoesNotExist:
        return _error("Zona/departamento invalido.")
    except PlanningError as exc:
        return _error(str(exc))


@login_required
@require_http_methods(["GET", "POST"])
@role_policy
@idempotent
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
            name=required_text(payload["name"], "Nombre"),
            product_type=product_type,
            presentation=str(payload.get("presentation", "")).strip(),
            unit_price=decimal_field(payload["unit_price"], "Precio"),
            unit_weight_kg=decimal_field(payload.get("unit_weight_kg", "1.00"), "Peso"),
            is_active=bool(payload.get("is_active", True)),
        )
        return _ok({"product": _serialize_product(product)}, status=201)
    except KeyError as exc:
        return _error(f"Falta el campo requerido: {exc.args[0]}")
    except Exception as exc:
        return _error(str(exc))


@login_required
@require_http_methods(["GET", "POST"])
@role_policy
@idempotent
def api_drivers(request: HttpRequest):
    if request.method == "GET":
        drivers = Driver.objects.select_related("user").all()
        if _get_role(request) == UserProfile.Role.DRIVER:
            drivers = drivers.filter(user=request.user)
        return _ok({"drivers": [_serialize_driver(d) for d in drivers]})

    perm_error = _require_role(request, UserProfile.Role.ADMIN, UserProfile.Role.SUPERVISOR)
    if perm_error:
        return perm_error

    try:
        payload = _parse_json(request)
        driver = Driver.objects.create(
            name=required_text(payload["name"], "Nombre"),
            phone=str(payload.get("phone", "")).strip(),
            license_number=required_text(payload["license_number"], "Licencia"),
            is_active=bool(payload.get("is_active", True)),
        )
        return _ok({"driver": _serialize_driver(driver)}, status=201)
    except KeyError as exc:
        return _error(f"Falta el campo requerido: {exc.args[0]}")
    except Exception as exc:
        return _error(str(exc))


@login_required
@require_http_methods(["GET", "POST"])
@role_policy
@idempotent
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
            plate=required_text(payload["plate"], "Placa").upper(),
            model=required_text(payload["model"], "Modelo"),
            capacity_kg=decimal_field(payload["capacity_kg"], "Capacidad"),
            fuel_efficiency_km_l=decimal_field(payload["fuel_efficiency_km_l"], "Rendimiento"),
            cost_per_km=decimal_field(payload["cost_per_km"], "Costo por kilometro", allow_zero=True),
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
@role_policy
@idempotent
def api_orders(request: HttpRequest):
    if request.method == "GET":
        orders = (
            Order.objects.select_related("origin", "destination", "store")
            .prefetch_related("items__product", "payments", "payment_allocations")
            .select_related("created_by")
            .all()
        )
        if _get_role(request) == UserProfile.Role.DRIVER:
            orders = orders.filter(trips__driver__user=request.user).distinct()
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

    perm_error = _require_role(request, UserProfile.Role.ADMIN, UserProfile.Role.SUPERVISOR, UserProfile.Role.SELLER)
    if perm_error:
        return perm_error

    try:
        payload = _parse_json(request)
        origin = Department.objects.get(pk=payload["origin_id"])
        store = None
        store_id = payload.get("store_id")
        if not store_id:
            return _error("Selecciona el cliente del pedido de agua o gas.")
        if store_id:
            store = Store.objects.select_related("department").get(pk=store_id, is_active=True)
            destination = store.department
        else:
            destination = Department.objects.get(pk=payload["destination_id"])
        if store is None and origin.id == destination.id:
            return _error("Origen y destino no pueden ser iguales.")

        items_payload = payload.get("items") or []
        if not isinstance(items_payload, list) or not items_payload:
            return _error("El pedido debe incluir al menos un producto de agua o gas.")
        if payload.get("priority", Order.Priority.NORMAL) not in Order.Priority.values:
            return _error("Prioridad invalida.")
        order = Order.objects.create(
            origin=origin,
            destination=destination,
            store=store,
            weight_kg=Decimal(str(payload.get("weight_kg", "1.00"))),
            package_count=int(payload.get("package_count", 1)),
            priority=payload.get("priority", Order.Priority.NORMAL),
            requested_for=operation_time(payload.get("occurred_at")),
            created_by=request.user,
            status=Order.Status.PENDING,
        )
        if items_payload:
            total_weight = Decimal("0.00")
            total_packages = 0
            for item_payload in items_payload:
                product = Product.objects.get(pk=item_payload["product_id"], is_active=True)
                quantity = int(item_payload.get("quantity", 1))
                unit_price = Decimal(str(item_payload.get("unit_price", product.unit_price)))
                if quantity <= 0 or str(quantity) != str(item_payload.get("quantity", 1)):
                    return _error("La cantidad debe ser un entero positivo.")
                if not unit_price.is_finite() or unit_price <= 0 or unit_price != unit_price.quantize(Decimal("0.01")):
                    return _error("El precio debe ser positivo y tener hasta dos decimales.")
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
@require_http_methods(["POST"])
@role_policy
@idempotent
def api_order_action(request: HttpRequest, order_id: int):
    order = get_object_or_404(Order, pk=order_id)
    if order.store_id:
        Store.objects.select_for_update().get(pk=order.store_id)
    order = Order.objects.select_for_update().get(pk=order.pk)
    try:
        payload = _parse_json(request)
        if payload.get("action") != "cancel":
            return _error("Accion de pedido invalida.")
        if order.status not in {Order.Status.PENDING, Order.Status.ASSIGNED}:
            return _error("Solo se pueden cancelar pedidos pendientes o asignados.")
        if order.paid_amount > 0:
            return _error("El pedido tiene cobros registrados. Revisa esos cobros antes de cancelar; no se generan devoluciones automaticas.")
        order.status = Order.Status.CANCELED
        order.save(update_fields=["status", "updated_at"])
        for stop in order.route_stops.filter(trip__status__in=[Trip.Status.PLANNED, Trip.Status.IN_PROGRESS]):
            if stop.status == RouteStop.Status.DELIVERED:
                raise PlanningError("La entrega ya fue confirmada.")
            stop.status = RouteStop.Status.NOT_DELIVERED
            stop.observation = "Pedido cancelado por el responsable de la ruta."
            stop.save(update_fields=["status", "observation", "updated_at"])
            TripEvent.objects.create(trip=stop.trip, stop=stop, recorded_by=request.user,
                                     occurred_at=operation_time(payload.get("occurred_at")), note=f"Pedido {order.code} cancelado.")
        return _ok({"order": _serialize_order(order)})
    except PlanningError as exc:
        return _error(str(exc))


@login_required
@require_http_methods(["GET"])
def api_trips(request: HttpRequest):
    trips = (
        Trip.objects.select_related("vehicle", "driver", "origin", "destination")
        .prefetch_related("orders__origin", "orders__destination", "orders__store", "orders__items__product", "orders__payments", "orders__payment_allocations", "stops__order", "stops__store", "events")
        .all()
    )
    role = _get_role(request)
    if role == UserProfile.Role.DRIVER:
        trips = trips.filter(driver__user=request.user)
    elif role == UserProfile.Role.SELLER:
        trips = trips.none()
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
@role_policy
@idempotent
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

        trip = TripPlanner.plan_trip(vehicle=vehicle, orders=orders, driver=driver, algorithm=algorithm, recorded_by=request.user)
        trip = (
            Trip.objects.select_related("vehicle", "driver", "origin", "destination")
            .prefetch_related("orders__origin", "orders__destination", "orders__store", "orders__items__product", "orders__payments", "orders__payment_allocations", "stops__order", "stops__store", "events")
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
@role_policy
@idempotent
def api_trip_action(request: HttpRequest, trip_id: int):
    trip = get_object_or_404(
        Trip.objects.select_related("vehicle", "driver", "origin", "destination").prefetch_related(
            "orders__origin", "orders__destination", "orders__store", "orders__items__product", "orders__payments", "orders__payment_allocations", "stops__order", "stops__store", "events"
        ),
        pk=trip_id,
    )
    perm_error = _require_role(request, UserProfile.Role.ADMIN, UserProfile.Role.SUPERVISOR, UserProfile.Role.DRIVER)
    if perm_error:
        return perm_error
    assignment_error = _require_assigned_trip(request, trip)
    if assignment_error:
        return assignment_error

    try:
        payload = _parse_json(request)
        action = payload.get("action")
        if action == "start":
            TripLifecycleService.start_trip(trip, recorded_by=request.user)
        elif action == "complete":
            TripLifecycleService.complete_trip(trip, recorded_by=request.user)
        elif action == "cancel":
            if _get_role(request) == UserProfile.Role.DRIVER:
                return _error("El repartidor no puede cancelar una ruta; solicita la cancelacion al supervisor.", 403)
            TripLifecycleService.cancel_trip(trip, recorded_by=request.user)
        else:
            return _error("Acción inválida. Usa: start, complete o cancel.")

        trip.refresh_from_db()
        trip = (
            Trip.objects.select_related("vehicle", "driver", "origin", "destination")
            .prefetch_related("orders__origin", "orders__destination", "orders__store", "orders__items__product", "orders__payments", "orders__payment_allocations", "stops__order", "stops__store", "events")
            .get(pk=trip.pk)
        )
        return _ok({"trip": _serialize_trip(trip)})
    except PlanningError as exc:
        return _error(str(exc))


@login_required
@require_http_methods(["POST"])
@role_policy
@idempotent
def api_trip_event(request: HttpRequest, trip_id: int):
    trip = get_object_or_404(Trip, pk=trip_id)
    assignment_error = _require_assigned_trip(request, trip)
    if assignment_error:
        return assignment_error
    try:
        payload = _parse_json(request)
        note = str(payload.get("note", ""))
        event = TripLifecycleService.add_event(trip, note)
        event.recorded_by = request.user
        event.occurred_at = operation_time(payload.get("occurred_at"))
        event.save(update_fields=["recorded_by", "occurred_at"])
        return _ok({"event": _serialize_event(event)}, status=201)
    except PlanningError as exc:
        return _error(str(exc))


@login_required
@require_http_methods(["POST"])
@role_policy
@idempotent
def api_route_stop(request: HttpRequest, trip_id: int, stop_id: int):
    get_object_or_404(Trip.objects.select_for_update(), pk=trip_id)
    stop = get_object_or_404(RouteStop.objects.select_related("trip", "order", "store"), pk=stop_id, trip_id=trip_id)
    assignment_error = _require_assigned_trip(request, stop.trip)
    if assignment_error:
        return assignment_error
    try:
        payload = _parse_json(request)
        status = payload.get("status", RouteStop.Status.DELIVERED)
        if status not in [choice[0] for choice in RouteStop.Status.choices]:
            return _error("Estado de parada invalido.")
        if stop.trip.status != Trip.Status.IN_PROGRESS:
            return _error("Solo se registran resultados de entrega en una ruta en progreso. Inicia la ruta antes de registrar la visita.")
        location = parse_location(payload, prefix="delivery_")
        if _get_role(request) == UserProfile.Role.DRIVER and location is None:
            return _error("El repartidor debe capturar su ubicacion actual al registrar la entrega.")
        if location:
            stop.delivery_latitude, stop.delivery_longitude, stop.delivery_accuracy_m, stop.delivery_captured_at = location
        if stop.status == RouteStop.Status.DELIVERED and status != stop.status:
            return _error("Una entrega confirmada no puede reabrirse automaticamente.")
        previous_status = stop.status
        stop.status = status
        stop.observation = str(payload.get("observation", stop.observation)).strip()
        stop.delivered_at = (stop.delivered_at or operation_time(payload.get("occurred_at"))) if status == RouteStop.Status.DELIVERED else None
        stop.save(update_fields=["status", "observation", "delivered_at", "updated_at",
                                 "delivery_latitude", "delivery_longitude", "delivery_accuracy_m", "delivery_captured_at"])
        if stop.order:
            if status == RouteStop.Status.DELIVERED:
                stop.order.status = Order.Status.DELIVERED
            elif status == RouteStop.Status.NOT_DELIVERED:
                stop.order.status = Order.Status.PENDING
            stop.order.save(update_fields=["status", "updated_at"])
        event = TripEvent.objects.create(trip=stop.trip, stop=stop, recorded_by=request.user,
                                        occurred_at=operation_time(payload.get("occurred_at")),
                                        note=f"Parada {stop.sequence}: {previous_status} -> {status}. {stop.observation}")
        return _ok({"stop": _serialize_route_stop(stop), "event": _serialize_event(event)})
    except PlanningError as exc:
        return _error(str(exc))
    except Exception as exc:
        return _error(str(exc))


@login_required
@require_http_methods(["GET", "POST"])
@role_policy
@idempotent
def api_payments(request: HttpRequest):
    if request.method == "GET":
        payments = Payment.objects.select_related("store", "order", "trip", "driver", "recorded_by").prefetch_related("allocations").all()
        if _get_role(request) == UserProfile.Role.DRIVER:
            payments = payments.filter(Q(trip__driver__user=request.user) | Q(recorded_by=request.user)).distinct()
        store_id = request.GET.get("store_id")
        if store_id:
            payments = payments.filter(store_id=store_id)
        return _ok({"payments": [_serialize_payment(payment) for payment in payments]})

    try:
        payload = _parse_json(request)
        if _get_role(request) == UserProfile.Role.DRIVER:
            driver = _assigned_driver(request)
            if driver is None or not payload.get("trip_id"):
                return _error("El cobro del repartidor debe estar asociado a una de sus rutas.")
            trip = get_object_or_404(Trip, pk=payload["trip_id"])
            assignment_error = _require_assigned_trip(request, trip)
            if assignment_error:
                return assignment_error
            payload["driver_id"] = driver.pk
        payment, duplicate = record_collection(payload, request.user)
        return _ok({"payment": _serialize_payment(payment), "duplicate": duplicate}, status=200 if duplicate else 201)
    except (PlanningError, KeyError) as exc:
        return _error(str(exc))



@login_required
@require_http_methods(["GET"])
def api_balances(request: HttpRequest):
    orders = Order.objects.select_related("store").prefetch_related("items", "payments", "payment_allocations").filter(store__isnull=False).exclude(status=Order.Status.CANCELED)
    if _get_role(request) == UserProfile.Role.DRIVER:
        orders = orders.filter(trips__driver__user=request.user).distinct()
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

    legacy = Payment.objects.filter(order__isnull=True, allocations__isnull=True).exclude(payment_type=Payment.PaymentType.CREDIT)
    for payment in legacy:
        if payment.store_id in balances:
            balances[payment.store_id]["paid_total"] += payment.amount
    payload = []
    for row in balances.values():
        row["balance_due"] = max(row["sales_total"] - row["paid_total"], Decimal("0.00"))
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
    orders = Order.objects.prefetch_related("items", "payments", "payment_allocations").exclude(status=Order.Status.CANCELED)
    trips = Trip.objects.all()
    payments = Payment.objects.all()
    if _get_role(request) == UserProfile.Role.DRIVER:
        orders = orders.filter(trips__driver__user=request.user).distinct()
        trips = trips.filter(driver__user=request.user)
        payments = payments.filter(Q(trip__driver__user=request.user) | Q(recorded_by=request.user)).distinct()
    if date_from:
        orders = orders.filter(requested_for__date__gte=date_from)
        trips = trips.filter(created_at__date__gte=date_from)
        payments = payments.filter(occurred_at__date__gte=date_from)
    if date_to:
        orders = orders.filter(requested_for__date__lte=date_to)
        trips = trips.filter(created_at__date__lte=date_to)
        payments = payments.filter(occurred_at__date__lte=date_to)

    sales_total = sum((order.total_amount for order in orders), Decimal("0.00"))
    paid_total = payments.exclude(payment_type=Payment.PaymentType.CREDIT).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
    delivered_orders = orders.filter(status=Order.Status.DELIVERED).count()
    pending_orders = orders.filter(status=Order.Status.PENDING).count()
    return _ok({
        "report": {
            "sales_total": _as_float(sales_total),
            "paid_total": _as_float(paid_total),
            "balance_due": _as_float(sum((order.balance_due for order in orders), Decimal("0.00"))),
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
@role_policy
@idempotent
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
        fp.regular_gtq_gal = decimal_field(payload["regular_gtq_gal"], "Precio de combustible")
        fp.super_gtq_gal = decimal_field(payload["super_gtq_gal"], "Precio de combustible")
        fp.diesel_gtq_gal = decimal_field(payload["diesel_gtq_gal"], "Precio de combustible")
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
    except (KeyError, ValueError, PlanningError) as exc:
        return _error(f"Datos inválidos: {exc}")


def method_not_allowed(_: HttpRequest):
    return HttpResponseNotAllowed(["GET", "POST"])
