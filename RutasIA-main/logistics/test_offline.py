import json
import uuid
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from logistics.application.services import TripLifecycleService, TripPlanner
from logistics.models import Department, Driver, MutationReceipt, Order, Payment, Product, RouteStop, Store, TripEvent, UserProfile, Vehicle


class OfflineApiTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user("dispatcher", password="test-password")
        UserProfile.objects.create(user=self.user, role=UserProfile.Role.SUPERVISOR)
        self.client.force_login(self.user)
        self.department = Department.objects.create(code="GUA", name="Guatemala", latitude="14.63", longitude="-90.51")
        self.store_payload = {"name": "Tienda GPS", "department_id": self.department.pk,
                              "latitude": 14.634915, "longitude": -90.506882, "accuracy_m": 12.5,
                              "captured_at": timezone.now().isoformat()}
        self.store = Store.objects.create(name="Cliente", department=self.department, latitude="14.63", longitude="-90.51")
        self.product = Product.objects.create(name="Garrafon", unit_price=20, unit_weight_kg=20)
        self.order = Order.objects.create(origin=self.department, destination=self.department, store=self.store, weight_kg=20)
        self.vehicle = Vehicle.objects.create(plate="TEST-GPS", model="Reparto", capacity_kg=1000,
                                              fuel_efficiency_km_l=10, cost_per_km=2)

    def post(self, url, payload, key=None, **headers):
        return self.client.post(url, json.dumps(payload), content_type="application/json",
                                HTTP_IDEMPOTENCY_KEY=str(key or uuid.uuid4()), **headers)

    def test_store_replay_returns_same_record_and_location(self):
        key = uuid.uuid4()
        first = self.post("/api/stores/", self.store_payload, key)
        second = self.post("/api/stores/", self.store_payload, key)
        self.assertEqual(first.status_code, 201)
        self.assertEqual(first.json(), second.json())
        self.assertEqual(Store.objects.filter(name="Tienda GPS").count(), 1)
        self.assertEqual(first.json()["store"]["location_accuracy_m"], 12.5)

    def test_reusing_key_for_different_request_is_rejected(self):
        key = uuid.uuid4()
        self.post("/api/stores/", self.store_payload, key)
        response = self.post("/api/stores/", {**self.store_payload, "name": "Otra tienda"}, key)
        self.assertEqual(response.status_code, 409)
        self.assertFalse(Store.objects.filter(name="Otra tienda").exists())

    def test_invalid_coordinates_do_not_create_store(self):
        for latitude, longitude in [(91, 0), (0, -181), ("NaN", 0), (None, None)]:
            response = self.post("/api/stores/", {**self.store_payload, "latitude": latitude, "longitude": longitude})
            self.assertEqual(response.status_code, 400)
        self.assertFalse(MutationReceipt.objects.exists())

    def test_failed_order_rolls_back_partial_items(self):
        before = Order.objects.count()
        response = self.post("/api/orders/", {"origin_id": self.department.pk, "store_id": self.store.pk,
            "items": [{"product_id": self.product.pk, "quantity": 1}, {"product_id": 999999, "quantity": 1}]})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Order.objects.count(), before)
        self.assertFalse(MutationReceipt.objects.exists())

    def test_order_and_payment_replay(self):
        key = uuid.uuid4()
        payload = {"origin_id": self.department.pk, "store_id": self.store.pk,
                   "items": [{"product_id": self.product.pk, "quantity": 2}]}
        first = self.post("/api/orders/", payload, key)
        self.assertEqual(first.status_code, 201)
        self.assertEqual(self.post("/api/orders/", payload, key).json(), first.json())
        payment = {"store_id": self.store.pk, "order_id": first.json()["order"]["id"],
                   "amount": 15, "uuid": str(uuid.uuid4()), "sync_status": "pending"}
        key = uuid.uuid4()
        paid = self.post("/api/payments/", payment, key)
        self.assertEqual(paid.status_code, 201)
        self.assertEqual(self.post("/api/payments/", payment, key).json(), paid.json())
        self.assertEqual(Payment.objects.count(), 1)
        self.assertEqual(paid.json()["payment"]["sync_status"], "synced")
        order = Order.objects.get(pk=payment["order_id"])
        self.assertEqual(order.balance_due, Decimal("25.00"))

    def test_negative_payment_is_rejected(self):
        response = self.post("/api/payments/", {"store_id": self.store.pk, "amount": -10})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Payment.objects.exists())

    def test_assigned_driver_can_capture_delivery_without_changing_store_coordinates(self):
        driver = Driver.objects.create(user=self.user, name="Repartidor", license_number="GPS-01")
        trip = TripPlanner.plan_trip(self.vehicle, Order.objects.filter(pk=self.order.pk), driver=driver)
        TripLifecycleService.start_trip(trip)
        stop = trip.stops.get()
        self.user.profile.role = UserProfile.Role.DRIVER
        self.user.profile.save()
        payload = {"status": "delivered", "delivery_latitude": 0, "delivery_longitude": 0,
                   "delivery_accuracy_m": 8, "delivery_captured_at": timezone.now().isoformat()}
        key = uuid.uuid4()
        first = self.post(f"/api/trips/{trip.pk}/stops/{stop.pk}/", payload, key)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(self.post(f"/api/trips/{trip.pk}/stops/{stop.pk}/", payload, key).json(), first.json())
        stop.refresh_from_db()
        self.assertEqual(stop.delivery_latitude, 0)
        self.assertEqual(first.json()["stop"]["delivery_longitude"], 0)
        self.assertEqual(stop.latitude, Decimal(self.store.latitude))
        self.assertEqual(stop.status, RouteStop.Status.DELIVERED)

    def test_completing_trip_preserves_failed_delivery_and_capture_time(self):
        other = Order.objects.create(origin=self.department, destination=self.department, store=self.store, weight_kg=20)
        trip = TripPlanner.plan_trip(self.vehicle, Order.objects.filter(pk__in=[self.order.pk, other.pk]))
        TripLifecycleService.start_trip(trip)
        stop = trip.stops.get(order=self.order)
        stop.status = RouteStop.Status.NOT_DELIVERED
        stop.save()
        delivered = trip.stops.get(order=other)
        actual_time = timezone.now() - timedelta(hours=2)
        delivered.status = RouteStop.Status.DELIVERED
        delivered.delivered_at = actual_time
        delivered.save()
        self.order.status = Order.Status.PENDING
        self.order.save()
        TripLifecycleService.complete_trip(trip)
        self.order.refresh_from_db()
        stop.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.PENDING)
        self.assertEqual(stop.status, RouteStop.Status.NOT_DELIVERED)
        delivered.refresh_from_db()
        self.assertEqual(delivered.delivered_at, actual_time)

    def test_closed_trip_rejects_new_stop_mutation(self):
        trip = TripPlanner.plan_trip(self.vehicle, Order.objects.filter(pk=self.order.pk))
        TripLifecycleService.start_trip(trip)
        stop = trip.stops.get()
        stop.status = RouteStop.Status.DELIVERED
        stop.save(update_fields=["status"])
        TripLifecycleService.complete_trip(trip)
        response = self.post(f"/api/trips/{trip.pk}/stops/{stop.pk}/", {"status": "not_delivered"})
        self.assertEqual(response.status_code, 400)

    def test_event_and_trip_start_replays_are_safe(self):
        trip = TripPlanner.plan_trip(self.vehicle, Order.objects.filter(pk=self.order.pk))
        key = uuid.uuid4()
        first = self.post(f"/api/trips/{trip.pk}/action/", {"action": "start"}, key)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(self.post(f"/api/trips/{trip.pk}/action/", {"action": "start"}, key).json(), first.json())
        key = uuid.uuid4()
        for _ in range(2):
            self.assertEqual(self.post(f"/api/trips/{trip.pk}/events/", {"note": "Visita offline"}, key).status_code, 201)
        self.assertEqual(TripEvent.objects.filter(note="Visita offline").count(), 1)

    def test_session_expiry_is_json_and_account_switch_is_blocked(self):
        response = self.client.get("/api/me/", HTTP_X_FLAMIA_USER_ID="999999")
        self.assertEqual(response.status_code, 409)
        self.client.logout()
        response = self.client.get("/api/me/")
        self.assertEqual(response.status_code, 401)
        self.assertFalse(response.json()["ok"])

    def test_seller_can_create_store_with_exact_location(self):
        self.user.profile.role = UserProfile.Role.SELLER
        self.user.profile.save()
        response = self.post("/api/stores/", self.store_payload)
        self.assertEqual(response.status_code, 201)
        self.assertTrue(Store.objects.filter(name="Tienda GPS", created_by=self.user).exists())
