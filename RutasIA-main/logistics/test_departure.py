import json
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from logistics.models import Department, Order, Product, Store, UserProfile


class OrderDepartureLocationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("supervisor", password="pass123")
        UserProfile.objects.create(user=self.user, role=UserProfile.Role.SUPERVISOR)
        self.client.force_login(self.user)
        self.department = Department.objects.create(code="GUA", name="Guatemala", latitude="14.63", longitude="-90.51")
        self.store = Store.objects.create(name="Tienda", department=self.department, latitude="14.63", longitude="-90.51")
        self.product = Product.objects.create(name="Agua", unit_price=Decimal("20"), unit_weight_kg=Decimal("20"))

    def create_order(self, **departure):
        payload = {
            "origin_id": self.department.pk, "store_id": self.store.pk,
            "items": [{"product_id": self.product.pk, "quantity": 1, "unit_price": "20.00"}],
            **departure,
        }
        return self.client.post("/api/orders/", data=json.dumps(payload), content_type="application/json")

    def test_gps_departure_is_saved_with_accuracy(self):
        captured_at = timezone.now().isoformat()
        response = self.create_order(departure_latitude=14.634915, departure_longitude=-90.506882,
                                     departure_accuracy_m=8.5, departure_captured_at=captured_at)
        self.assertEqual(response.status_code, 201)
        order = Order.objects.get()
        self.assertEqual(order.departure_latitude, Decimal("14.634915"))
        self.assertEqual(order.departure_longitude, Decimal("-90.506882"))
        self.assertEqual(order.departure_accuracy_m, 8.5)
        self.assertIsNotNone(order.departure_captured_at)
        self.assertEqual(response.json()["order"]["departure_latitude"], 14.634915)

    def test_typed_coordinates_are_saved_without_accuracy(self):
        response = self.create_order(departure_latitude=14.6, departure_longitude=-90.5)
        self.assertEqual(response.status_code, 201)
        order = Order.objects.get()
        self.assertEqual(order.departure_latitude, Decimal("14.6"))
        self.assertIsNone(order.departure_accuracy_m)
        self.assertIsNone(order.departure_captured_at)

    def test_departure_is_optional(self):
        response = self.create_order()
        self.assertEqual(response.status_code, 201)
        self.assertIsNone(Order.objects.get().departure_latitude)
        self.assertIsNone(response.json()["order"]["departure_latitude"])

    def test_incomplete_or_invalid_departure_creates_no_order(self):
        self.assertEqual(self.create_order(departure_latitude=14.6).status_code, 400)
        self.assertEqual(self.create_order(departure_latitude=200, departure_longitude=-90.5).status_code, 400)
        self.assertFalse(Order.objects.exists())
