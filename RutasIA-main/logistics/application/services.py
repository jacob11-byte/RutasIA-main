from __future__ import annotations

from decimal import Decimal
from typing import Iterable

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from logistics.models import Department, Driver, FuelPrice, Order, RouteStop, Trip, TripEvent, TripOrder, Vehicle
from logistics.domain.exceptions import PlanningError
from logistics.domain.services import AStarOptimizer, RouteOptimizer, to_decimal, ZERO

LITERS_PER_GALLON = Decimal("3.78541")


class TripPlanner:
    @staticmethod
    def _validate_orders(orders: Iterable[Order]) -> list[Order]:
        order_list = list(orders)
        if not order_list:
            raise PlanningError("Debes seleccionar al menos un pedido.")

        pending_only = [o for o in order_list if o.status == Order.Status.PENDING]
        if len(pending_only) != len(order_list):
            raise PlanningError("Todos los pedidos deben estar en estado pendiente.")

        first = order_list[0]
        same_route = True or all(
            o.origin_id == first.origin_id and o.destination_id == first.destination_id for o in order_list
        )
        if not same_route:
            raise PlanningError("Para esta versión, los pedidos deben compartir mismo origen y destino.")

        return order_list

    @staticmethod
    def _ordered_stops(order_list: list[Order], optimizer) -> list[Order]:
        pending = order_list[:]
        current_id = pending[0].origin_id
        ordered: list[Order] = []
        while pending:
            best_order = None
            best_distance = None
            for order in pending:
                try:
                    _nodes, distance = optimizer.shortest_path(current_id, order.destination_id)
                except PlanningError:
                    continue
                if best_distance is None or distance < best_distance:
                    best_order = order
                    best_distance = distance
            if best_order is None:
                raise PlanningError("No existe una ruta conectada para una o mas paradas seleccionadas.")
            ordered.append(best_order)
            pending.remove(best_order)
            current_id = best_order.destination_id
        return ordered

    @staticmethod
    def _build_route(order_list: list[Order], optimizer) -> tuple[list[int], Decimal, list[Order]]:
        ordered_orders = TripPlanner._ordered_stops(order_list, optimizer)
        current_id = ordered_orders[0].origin_id
        route_node_ids: list[int] = []
        total_distance = ZERO

        for order in ordered_orders:
            node_ids, distance = optimizer.shortest_path(current_id, order.destination_id)
            if route_node_ids and node_ids and route_node_ids[-1] == node_ids[0]:
                route_node_ids.extend(node_ids[1:])
            else:
                route_node_ids.extend(node_ids)
            total_distance += distance
            current_id = order.destination_id

        return route_node_ids, to_decimal(total_distance), ordered_orders

    @classmethod
    @transaction.atomic
    def plan_trip(
        cls,
        vehicle: Vehicle,
        orders: QuerySet[Order],
        driver: Driver | None = None,
        algorithm: str = "dijkstra",
    ) -> Trip:
        if not vehicle.is_active:
            raise PlanningError("El vehículo seleccionado está inactivo.")

        order_list = cls._validate_orders(orders)
        total_weight = sum(Decimal(o.weight_kg) for o in order_list)
        if total_weight > Decimal(vehicle.capacity_kg):
            raise PlanningError(
                f"La carga total ({to_decimal(total_weight)} kg) excede la capacidad del vehículo."
            )

        if Decimal(vehicle.fuel_efficiency_km_l) <= ZERO:
            raise PlanningError("La eficiencia del vehículo debe ser mayor a 0.")

        optimizer = AStarOptimizer if algorithm == "astar" else RouteOptimizer
        node_ids, distance, ordered_orders = cls._build_route(order_list, optimizer)
        origin = ordered_orders[0].origin
        destination = ordered_orders[-1].destination

        fuel_liters = to_decimal(distance / Decimal(vehicle.fuel_efficiency_km_l))
        fuel_gallons = to_decimal(fuel_liters / LITERS_PER_GALLON)
        estimated_cost = to_decimal(distance * Decimal(vehicle.cost_per_km))

        fp = FuelPrice.current()
        fuel_price_gtq_gal = to_decimal(fp.regular_gtq_gal)
        estimated_fuel_cost_gtq = to_decimal(fuel_gallons * fuel_price_gtq_gal)

        node_name_lookup = Department.objects.in_bulk(node_ids)
        route_nodes = [node_name_lookup[node_id].name for node_id in node_ids]

        trip = Trip.objects.create(
            vehicle=vehicle,
            driver=driver,
            origin=origin,
            destination=destination,
            route_nodes=route_nodes,
            total_distance_km=distance,
            estimated_fuel_gallons=fuel_gallons,
            fuel_price_gtq_gal=fuel_price_gtq_gal,
            estimated_fuel_cost_gtq=estimated_fuel_cost_gtq,
            estimated_cost=estimated_cost,
            status=Trip.Status.PLANNED,
        )

        TripOrder.objects.bulk_create([TripOrder(trip=trip, order=order) for order in ordered_orders])
        RouteStop.objects.bulk_create([
            RouteStop(
                trip=trip,
                order=order,
                store=order.store,
                sequence=index,
                latitude=order.store.latitude if order.store else order.destination.latitude,
                longitude=order.store.longitude if order.store else order.destination.longitude,
            )
            for index, order in enumerate(ordered_orders, start=1)
        ])
        Order.objects.filter(id__in=[o.id for o in order_list]).update(status=Order.Status.ASSIGNED)
        algo_label = "A* (A-estrella)" if algorithm == "astar" else "Dijkstra"
        TripEvent.objects.create(
            trip=trip,
            note=f"Viaje planificado con {len(order_list)} pedido(s) usando {algo_label}. Ruta: {' -> '.join(route_nodes)}.",
        )
        return trip


class TripLifecycleService:
    @staticmethod
    @transaction.atomic
    def start_trip(trip: Trip) -> Trip:
        if trip.status != Trip.Status.PLANNED:
            raise PlanningError("Solo se puede iniciar un viaje planificado.")
        trip.status = Trip.Status.IN_PROGRESS
        trip.started_at = timezone.now()
        trip.save(update_fields=["status", "started_at", "updated_at"])
        trip.orders.update(status=Order.Status.IN_TRANSIT)
        trip.stops.filter(status=RouteStop.Status.PENDING).update(status=RouteStop.Status.PENDING)
        TripEvent.objects.create(trip=trip, note="Viaje iniciado.")
        return trip

    @staticmethod
    @transaction.atomic
    def complete_trip(trip: Trip) -> Trip:
        if trip.status not in {Trip.Status.IN_PROGRESS, Trip.Status.PLANNED}:
            raise PlanningError("Solo se puede completar un viaje planificado o en progreso.")
        trip.status = Trip.Status.COMPLETED
        if trip.started_at is None:
            trip.started_at = timezone.now()
        trip.completed_at = timezone.now()
        trip.save(update_fields=["status", "started_at", "completed_at", "updated_at"])
        trip.orders.update(status=Order.Status.DELIVERED)
        trip.stops.exclude(status=RouteStop.Status.NOT_DELIVERED).update(
            status=RouteStop.Status.DELIVERED,
            delivered_at=trip.completed_at,
        )
        TripEvent.objects.create(trip=trip, note="Viaje completado y pedidos marcados como entregados.")
        return trip

    @staticmethod
    @transaction.atomic
    def cancel_trip(trip: Trip) -> Trip:
        if trip.status == Trip.Status.COMPLETED:
            raise PlanningError("No se puede cancelar un viaje ya completado.")
        trip.status = Trip.Status.CANCELED
        trip.save(update_fields=["status", "updated_at"])
        trip.orders.exclude(status=Order.Status.DELIVERED).update(status=Order.Status.PENDING)
        trip.stops.exclude(status=RouteStop.Status.DELIVERED).update(status=RouteStop.Status.PENDING)
        TripEvent.objects.create(trip=trip, note="Viaje cancelado.")
        return trip

    @staticmethod
    def add_event(trip: Trip, note: str) -> TripEvent:
        if not note.strip():
            raise PlanningError("El evento no puede estar vacío.")
        return TripEvent.objects.create(trip=trip, note=note.strip())
