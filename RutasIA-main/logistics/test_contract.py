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

    def test_seller_can_create_stores_and_orders_but_not_change_catalogues(self):
        self.user.profile.role = "seller"
        self.user.profile.save()
        payload = {"store_id": self.store.pk, "origin_id": self.department.pk,
                   "items": [{"product_id": self.product.pk, "quantity": 1}]}
        self.assertEqual(self.post("/api/orders/", payload).status_code, 201)
        self.assertEqual(self.post("/api/stores/", {"name": "Nueva tienda", "department_id": self.department.pk,
            "latitude": 14.64, "longitude": -90.52}).status_code, 201)
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
        UserProfile.objects.create(user=other, role="seller")
        self.assertEqual(self.post(f"/api/users/{other.pk}/", {"role": "supervisor", "is_active": True}).status_code, 200)
        other.profile.refresh_from_db()
        self.assertEqual(other.profile.role, "supervisor")
        self.assertEqual(self.post(f"/api/users/{self.user.pk}/", {"role": "seller"}).status_code, 400)
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


class EmployeeAccountWorkflowTests(TestCase):
    password = "Cuenta-Segura-Flamia-2026!"

    def signup(self, username, role, **extra):
        return self.client.post("/accounts/signup/", {
            "username": username,
            "first_name": "Empleado",
            "last_name": "Flamia",
            "email": f"{username}@example.test",
            "role": role,
            "phone": "5555-0101",
            "license_number": extra.get("license_number", ""),
            "password1": self.password,
            "password2": self.password,
        })

    def test_public_signup_creates_pending_seller_and_driver_accounts(self):
        self.assertEqual(self.signup("vendedor", "seller").status_code, 302)
        seller = User.objects.get(username="vendedor")
        self.assertFalse(seller.is_active)
        self.assertEqual(seller.profile.role, UserProfile.Role.SELLER)
        self.assertFalse(Driver.objects.filter(user=seller).exists())

        self.assertEqual(self.signup("repartidor", "driver", license_number="LIC-900").status_code, 302)
        driver_user = User.objects.get(username="repartidor")
        self.assertFalse(driver_user.is_active)
        self.assertEqual(driver_user.profile.role, UserProfile.Role.DRIVER)
        self.assertEqual(driver_user.driver_profile.license_number, "LIC-900")
        self.assertFalse(driver_user.driver_profile.is_active)

        self.assertEqual(self.signup("intruso", "admin").status_code, 200)
        self.assertFalse(User.objects.filter(username="intruso").exists())

    def test_admin_approval_activates_driver_account_and_operational_record(self):
        self.signup("repartidor", "driver", license_number="LIC-901")
        driver_user = User.objects.get(username="repartidor")
        admin = User.objects.create_superuser("raiz", "raiz@example.test", self.password)
        self.client.force_login(admin)
        response = self.client.post(
            f"/api/users/{driver_user.pk}/",
            json.dumps({"role": "driver", "is_active": True}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        driver_user.refresh_from_db()
        driver_user.driver_profile.refresh_from_db()
        self.assertTrue(driver_user.is_active)
        self.assertTrue(driver_user.driver_profile.is_active)

    def test_driver_sees_and_updates_only_assigned_route_with_gps(self):
        department = Department.objects.create(code="GUA", name="Guatemala", latitude=14.60, longitude=-90.50)
        product = Product.objects.create(name="Gas", product_type="gas", unit_price=100, unit_weight_kg=25)
        vehicle = Vehicle.objects.create(plate="DRV-001", model="Reparto", capacity_kg=500,
                                         fuel_efficiency_km_l=10, cost_per_km=2)
        users = []
        trips = []
        for index, longitude in enumerate((-90.51, -90.53), start=1):
            user = User.objects.create_user(f"driver{index}", password=self.password)
            UserProfile.objects.create(user=user, role=UserProfile.Role.DRIVER)
            driver = Driver.objects.create(user=user, name=f"Repartidor {index}", license_number=f"D-{index}")
            store = Store.objects.create(name=f"Tienda {index}", department=department,
                                         latitude=14.60, longitude=longitude)
            order = Order.objects.create(store=store, origin=department, destination=department, weight_kg=25)
            OrderItem.objects.create(order=order, product=product, quantity=1, unit_price=100)
            trips.append(TripPlanner.plan_trip(vehicle, Order.objects.filter(pk=order.pk), driver=driver))
            users.append(user)

        self.client.force_login(users[0])
        visible = self.client.get("/api/trips/").json()["trips"]
        self.assertEqual([row["id"] for row in visible], [trips[0].pk])
        self.assertEqual(self.client.post(f"/api/trips/{trips[1].pk}/action/", json.dumps({"action": "start"}),
                                          content_type="application/json").status_code, 403)
        self.assertEqual(self.client.post(f"/api/trips/{trips[0].pk}/action/", json.dumps({"action": "start"}),
                                          content_type="application/json").status_code, 200)
        stop = trips[0].stops.get()
        url = f"/api/trips/{trips[0].pk}/stops/{stop.pk}/"
        self.assertEqual(self.client.post(url, json.dumps({"status": "delivered"}), content_type="application/json").status_code, 400)
        response = self.client.post(url, json.dumps({
            "status": "delivered", "delivery_latitude": 14.60, "delivery_longitude": -90.51,
            "delivery_accuracy_m": 8, "delivery_captured_at": timezone.now().isoformat(),
        }), content_type="application/json")
        self.assertEqual(response.status_code, 200)

    def test_exact_store_coordinates_determine_stop_order_inside_same_zone(self):
        admin = User.objects.create_user("planner", password=self.password)
        UserProfile.objects.create(user=admin, role=UserProfile.Role.SUPERVISOR)
        department = Department.objects.create(code="GUA", name="Guatemala", latitude=14.60, longitude=-90.50)
        near = Store.objects.create(name="Cercana", department=department, latitude=14.601, longitude=-90.501)
        far = Store.objects.create(name="Lejana", department=department, latitude=14.70, longitude=-90.70)
        product = Product.objects.create(name="Agua", unit_price=20, unit_weight_kg=20)
        near_order = Order.objects.create(store=near, origin=department, destination=department, weight_kg=20)
        far_order = Order.objects.create(store=far, origin=department, destination=department, weight_kg=20)
        for order in (near_order, far_order):
            OrderItem.objects.create(order=order, product=product, quantity=1, unit_price=20)
        vehicle = Vehicle.objects.create(plate="GPS-ORDER", model="Reparto", capacity_kg=500,
                                         fuel_efficiency_km_l=10, cost_per_km=2)
        # The default queryset order presents the far order first; GPS must still choose the near store.
        trip = TripPlanner.plan_trip(vehicle, Order.objects.filter(pk__in=[near_order.pk, far_order.pk]))
        self.assertEqual(list(trip.stops.order_by("sequence").values_list("store__name", flat=True)), ["Cercana", "Lejana"])
        self.assertGreater(trip.total_distance_km, 0)
