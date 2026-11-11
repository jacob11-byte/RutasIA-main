"""Permanent deletion limited to records without operational history.

Records referenced by orders, routes or collections are kept so balances and
reports stay consistent; the caller is told to deactivate or cancel instead.
"""
from __future__ import annotations

from logistics.domain.exceptions import PlanningError
from logistics.models import Department, Driver, Order, Product, Store, Vehicle


def delete_store(store_id: int) -> None:
    store = Store.objects.select_for_update().get(pk=store_id)
    if store.orders.exists() or store.payments.exists() or store.route_stops.exists():
        raise PlanningError("La tienda tiene pedidos, cobros o visitas registradas. Desactivala desde Editar para conservar su historial.")
    store.delete()


def delete_order(order_id: int) -> None:
    # Same lock order as order cancellation and payments: store first, then order.
    store_id = Order.objects.values_list("store_id", flat=True).get(pk=order_id)
    if store_id:
        Store.objects.select_for_update().get(pk=store_id)
    order = Order.objects.select_for_update().get(pk=order_id)
    if order.status not in {Order.Status.PENDING, Order.Status.CANCELED}:
        raise PlanningError("Solo se pueden eliminar pedidos pendientes o cancelados.")
    if order.trips.exists() or order.route_stops.exists():
        raise PlanningError("El pedido ya forma parte de una ruta. Cancelalo para conservar el historial de la ruta.")
    if order.paid_amount > 0 or order.payments.exists() or order.payment_allocations.exists():
        raise PlanningError("El pedido tiene cobros registrados y no se puede eliminar.")
    order.delete()


def delete_product(product_id: int) -> None:
    product = Product.objects.select_for_update().get(pk=product_id)
    if product.order_items.exists():
        raise PlanningError("El producto aparece en pedidos registrados. Desactivalo para que ya no se pueda vender.")
    product.delete()


def delete_vehicle(vehicle_id: int) -> None:
    vehicle = Vehicle.objects.select_for_update().get(pk=vehicle_id)
    if vehicle.trips.exists():
        raise PlanningError("El vehiculo tiene rutas registradas. Desactivalo para que no se use en nuevas rutas.")
    vehicle.delete()


def delete_driver(driver_id: int) -> None:
    driver = Driver.objects.select_for_update().get(pk=driver_id)
    if driver.user_id:
        raise PlanningError("El repartidor tiene una cuenta de usuario. Desactiva su acceso en Usuarios.")
    if driver.trips.exists() or driver.collections.exists():
        raise PlanningError("El repartidor tiene rutas o cobros registrados y no se puede eliminar.")
    driver.delete()


def delete_department(department_id: int) -> None:
    department = Department.objects.select_for_update().get(pk=department_id)
    in_use = (
        department.stores.exists()
        or department.orders_origin.exists()
        or department.orders_destination.exists()
        or department.trips_origin.exists()
        or department.trips_destination.exists()
    )
    if in_use:
        raise PlanningError("La zona tiene tiendas, pedidos o rutas registradas y no se puede eliminar.")
    department.delete()


DELETERS = {
    "stores": delete_store,
    "orders": delete_order,
    "products": delete_product,
    "vehicles": delete_vehicle,
    "drivers": delete_driver,
    "departments": delete_department,
}
