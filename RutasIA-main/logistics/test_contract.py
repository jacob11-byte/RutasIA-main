import json
import uuid
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
from django.test import override_settings
from django.utils import timezone
from unittest.mock import patch

from logistics.application.services import TripLifecycleService, TripPlanner
from logistics.domain.exceptions import PlanningError
from logistics.models import Department, Driver, Order, OrderItem, Payment, PaymentAllocation, Product, Store, TripEvent, UserProfile, Vehicle


class DocumentContractTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user("encargado", password="Credencial-Segura-2026!")
        UserProfile.objects.create(user=self.user, role="admin")
        self.client.force_login(self.user)
        self.department = Department.objects.create(code="GUA", name="Guatemala")
        self.store = Store.objects.create(name="Cliente", department=self.department, latitude=14.63, longitude=-90.51)
        self.product = Product.objects.create(name="Agua", unit_price=20, unit_weight_kg=20)
        self.driver = Driver.objects.create(name="Repartidor", license_number="L-01")
        self.vehicle = Vehicle.objects.create(plate="C-TEST", model="Reparto", capacity_kg=1000, fuel_efficiency_km_l=10, cost_per_km=2, driver=self.driver)
        self.order = self.make_order()

    def tearDown(self):
        cache.clear()

    def make_order(self, quantity=2):
        order = Order.objects.create(store=self.store, origin=self.department, destination=self.department, weight_kg=20 * quantity)
        OrderItem.objects.create(order=order, product=self.product, quantity=quantity, unit_price=20)
        return order

    def post(self, url, payload, key=True):
        return self.client.post(url, json.dumps(payload), content_type="application/json",
                                **({"HTTP_IDEMPOTENCY_KEY": str(uuid.uuid4())} if key else {}))

    def payment(self, **kwargs):
        return self.post("/api/payments/", {"store_id": self.store.pk, "order_id": self.order.pk,
            "uuid": str(uuid.uuid4()), "amount": 10, **kwargs})

    def test_credit_is_not_money_received(self):
        response = self.payment(payment_type="credit", amount=0)
        self.assertEqual(response.status_code, 201)
        self.order.refresh_from_db()
        self.assertEqual(self.order.balance_due, 40)
        report = self.client.get("/api/reports/").json()["report"]
        self.assertEqual(report["paid_total"], 0)
        self.assertEqual(report["balance_due"], 40)
        self.assertEqual(self.payment(payment_type="credit", amount=40).status_code, 400)

    def test_complete_partial_and_overpayment_rules(self):
        for data in [{"amount": 0}, {"amount": 41}, {"amount": -1}, {"amount": 1.001}, {"amount": 10, "payment_type": "full_payment"}]:
            self.assertEqual(self.payment(**data).status_code, 400)
        self.assertEqual(self.payment(amount=15).status_code, 201)
        self.assertEqual(self.payment(amount=25, payment_type="full_payment").status_code, 201)
        self.assertEqual(self.client.get("/api/orders/").json()["orders"][0]["payment_status"], "paid")

    def test_customer_payment_settles_oldest_orders_without_losing_money(self):
        second = self.make_order(quantity=1)
        response = self.payment(order_id=None, amount=50)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Payment.objects.count(), 1)
        self.assertEqual(PaymentAllocation.objects.count(), 2)
        self.assertEqual(self.order.paid_amount, 40)
        self.assertEqual(second.paid_amount, 10)
        self.assertEqual(second.balance_due, 10)
        balance = self.client.get("/api/balances/").json()["balances"][0]
        self.assertEqual((balance["sales_total"], balance["paid_total"], balance["balance_due"]), (60, 50, 10))

    def test_uuid_replay_validates_the_transaction(self):
        key = str(uuid.uuid4())
        self.assertEqual(self.payment(uuid=key).status_code, 201)
        self.assertEqual(self.payment(uuid=key).status_code, 200)
        self.assertEqual(self.payment(uuid=key, amount=20).status_code, 400)
        self.assertEqual(Payment.objects.count(), 1)

    def test_actor_driver_and_field_date_are_recorded(self):
        stamp = timezone.now() - timedelta(days=2)
        response = self.payment(driver_id=self.driver.pk, occurred_at=stamp.isoformat())
        self.assertEqual(response.status_code, 201)
        payment = Payment.objects.get()
        self.assertEqual(payment.recorded_by, self.user)
        self.assertEqual(payment.driver, self.driver)
        self.assertEqual(payment.occurred_at, stamp)
        day = timezone.localtime(stamp).date()
        self.assertEqual(self.client.get(f"/api/reports/?date_from={day}&date_to={day}").json()["report"]["paid_total"], 10)

    def test_operator_can_create_documented_orders_but_not_change_catalogues(self):
        self.user.profile.role = "operator"
        self.user.profile.save()
        payload = {"store_id": self.store.pk, "origin_id": self.department.pk,
                   "items": [{"product_id": self.product.pk, "quantity": 1}]}
        self.assertEqual(self.post("/api/orders/", payload).status_code, 201)
        self.assertEqual(self.post("/api/products/", {"name": "Gas", "unit_price": 100}).status_code, 403)
        self.assertEqual(self.post("/api/trips/plan/", {}).status_code, 403)

    def test_parcel_orders_and_invalid_product_quantities_are_rejected(self):
        for payload in [{"origin_id": self.department.pk, "destination_id": self.department.pk},
                        {"origin_id": self.department.pk, "store_id": self.store.pk},
                        {"origin_id": self.department.pk, "store_id": self.store.pk, "items": [{"product_id": self.product.pk, "quantity": 0}]}]:
            self.assertEqual(self.post("/api/orders/", payload).status_code, 400)
        self.assertEqual(Order.objects.count(), 1)

    def test_partial_order_is_rolled_back_without_an_idempotency_header(self):
        response = self.post("/api/orders/", {"origin_id": self.department.pk, "store_id": self.store.pk,
            "items": [{"product_id": self.product.pk, "quantity": 1}, {"product_id": 999999, "quantity": 1}]}, key=False)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Order.objects.count(), 1)

    def test_admin_updates_roles_and_cannot_remove_own_access(self):
        other = User.objects.create_user("otro")
        UserProfile.objects.create(user=other, role="operator")
        self.assertEqual(self.post(f"/api/users/{other.pk}/", {"role": "supervisor", "is_active": True}).status_code, 200)
        other.profile.refresh_from_db()
        self.assertEqual(other.profile.role, "supervisor")
        self.assertEqual(self.post(f"/api/users/{self.user.pk}/", {"role": "operator"}).status_code, 400)
        self.user.profile.role = "supervisor"
        self.user.profile.save()
        self.assertEqual(self.post(f"/api/users/{other.pk}/", {"role": "admin"}).status_code, 403)

    def test_routes_have_one_dispatch_base_and_an_active_driver(self):
        other = self.make_order()
        other.origin = Department.objects.create(code="ESC", name="Escuintla")
        other.save()
        with self.assertRaises(PlanningError):
            TripPlanner.plan_trip(self.vehicle, Order.objects.all())
        self.driver.is_active = False
        self.driver.save()
        with self.assertRaises(PlanningError):
            TripPlanner.plan_trip(self.vehicle, Order.objects.filter(pk=self.order.pk))

    def test_delivery_audit_and_cancellation_preserve_confirmed_delivery(self):
        trip = TripPlanner.plan_trip(self.vehicle, Order.objects.filter(pk=self.order.pk), recorded_by=self.user)
        TripLifecycleService.start_trip(trip)
        stop = trip.stops.get()
        self.assertEqual(trip.driver, self.driver)
        self.assertEqual(self.post(f"/api/trips/{trip.pk}/stops/{stop.pk}/", {"status": "delivered", "observation": "Recibido por encargado"}).status_code, 200)
        event = TripEvent.objects.get(stop=stop)
        self.assertEqual(event.recorded_by, self.user)
        self.assertIn("Recibido por encargado", event.note)
        self.assertEqual(self.post(f"/api/trips/{trip.pk}/stops/{stop.pk}/", {"status": "pending"}).status_code, 400)
        TripLifecycleService.cancel_trip(trip, recorded_by=self.user)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "delivered")

    def test_failed_delivery_cannot_be_planned_again_while_old_route_is_open(self):
        trip = TripPlanner.plan_trip(self.vehicle, Order.objects.filter(pk=self.order.pk))
        TripLifecycleService.start_trip(trip)
        stop = trip.stops.get()
        self.post(f"/api/trips/{trip.pk}/stops/{stop.pk}/", {"status": "not_delivered"})
        with self.assertRaises(PlanningError):
            TripPlanner.plan_trip(self.vehicle, Order.objects.filter(pk=self.order.pk))
        TripLifecycleService.complete_trip(trip)
        new_trip = TripPlanner.plan_trip(self.vehicle, Order.objects.filter(pk=self.order.pk))
        self.assertNotEqual(trip.pk, new_trip.pk)

    def test_cancellation_is_real_and_not_reopened_by_trip_lifecycle(self):
        trip = TripPlanner.plan_trip(self.vehicle, Order.objects.filter(pk=self.order.pk))
        response = self.post(f"/api/orders/{self.order.pk}/action/", {"action": "cancel"})
        self.assertEqual(response.status_code, 200)
        TripLifecycleService.start_trip(trip)
        TripLifecycleService.complete_trip(trip)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "canceled")
        self.assertEqual(self.order.balance_due, 0)

    def test_cancellation_of_an_order_with_money_received_is_rejected(self):
        self.payment(amount=5)
        response = self.post(f"/api/orders/{self.order.pk}/action/", {"action": "cancel"})
        self.assertEqual(response.status_code, 400)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "pending")
        self.assertEqual(self.order.paid_amount, 5)

    def test_deployment_requires_explicit_configuration(self):
        from logistics.checks import production_configuration
        with patch.dict("os.environ", {}, clear=True), override_settings(DEBUG=True, SECRET_KEY="django-insecure-development", ALLOWED_HOSTS=["*"]):
            self.assertTrue(production_configuration(None))
        with patch.dict("os.environ", {"SECRET_KEY": "x" * 60, "DATABASE_URL": "postgresql://configured", "ALLOWED_HOSTS": "flamia.example", "CSRF_TRUSTED_ORIGINS": "https://flamia.example"}, clear=True), override_settings(DEBUG=False, SECRET_KEY="x" * 60, ALLOWED_HOSTS=["flamia.example"]):
            self.assertEqual(production_configuration(None), [])

    def test_django_superuser_has_administrative_access_without_profile(self):
        user = User.objects.create_superuser("administrador-raiz", "admin@example.test", "Credencial-Segura-2026!")
        self.client.force_login(user)
        self.assertEqual(self.client.get("/api/me/").json()["user"]["role"], "admin")
        self.assertEqual(self.client.get("/api/users/").status_code, 200)

    def test_route_must_be_started_before_recording_or_completing_deliveries(self):
        trip = TripPlanner.plan_trip(self.vehicle, Order.objects.filter(pk=self.order.pk))
        stop = trip.stops.get()
        self.assertEqual(self.post(f"/api/trips/{trip.pk}/stops/{stop.pk}/", {"status": "delivered"}).status_code, 400)
        self.assertEqual(self.post(f"/api/trips/{trip.pk}/action/", {"action": "complete"}).status_code, 400)
        self.assertEqual(self.post(f"/api/trips/{trip.pk}/action/", {"action": "start"}).status_code, 200)
        self.assertEqual(self.post(f"/api/trips/{trip.pk}/stops/{stop.pk}/", {"status": "delivered"}).status_code, 200)
