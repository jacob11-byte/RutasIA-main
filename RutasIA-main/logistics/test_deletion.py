from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase

from logistics.application.services import TripPlanner
from logistics.models import (
    Department, Driver, Order, OrderItem, Payment, Product, Store, UserProfile, Vehicle,
)


class DeletionApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("supervisor", password="pass123")
        UserProfile.objects.create(user=self.user, role=UserProfile.Role.SUPERVISOR)
        self.client.force_login(self.user)
        self.department = Department.objects.create(code="GUA", name="Guatemala", latitude="14.63", longitude="-90.51")
        self.store = Store.objects.create(name="Tienda", department=self.department, latitude="14.63", longitude="-90.51")
        self.product = Product.objects.create(name="Agua", unit_price=Decimal("20"), unit_weight_kg=Decimal("20"))
        self.vehicle = Vehicle.objects.create(plate="P-1", model="Pickup", capacity_kg=1000, fuel_efficiency_km_l=10, cost_per_km=2)

    def delete(self, kind, record_id):
        return self.client.post(f"/api/{kind}/{record_id}/delete/", data="{}", content_type="application/json")

    def make_order(self, store=None):
        order = Order.objects.create(origin=self.department, destination=self.department, store=store or self.store, weight_kg=20)
        OrderItem.objects.create(order=order, product=self.product, quantity=1, unit_price=Decimal("20"))
        return order

    def test_store_without_history_is_deleted(self):
        response = self.delete("stores", self.store.pk)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Store.objects.filter(pk=self.store.pk).exists())

    def test_store_with_orders_is_kept(self):
        self.make_order()
        response = self.delete("stores", self.store.pk)
        self.assertEqual(response.status_code, 400)
        self.assertIn("Desactivala", response.json()["error"])
        self.assertTrue(Store.objects.filter(pk=self.store.pk).exists())

    def test_pending_order_is_deleted_with_its_items(self):
        order = self.make_order()
        response = self.delete("orders", order.pk)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Order.objects.filter(pk=order.pk).exists())
        self.assertFalse(OrderItem.objects.filter(order_id=order.pk).exists())

    def test_order_in_route_is_kept(self):
        order = self.make_order()
        TripPlanner.plan_trip(self.vehicle, Order.objects.filter(pk=order.pk))
        order.refresh_from_db()
        order.status = Order.Status.CANCELED
        order.save(update_fields=["status"])
        response = self.delete("orders", order.pk)
        self.assertEqual(response.status_code, 400)
        self.assertTrue(Order.objects.filter(pk=order.pk).exists())

    def test_order_with_payment_is_kept(self):
        order = self.make_order()
        Payment.objects.create(store=self.store, order=order, amount=Decimal("5"))
        response = self.delete("orders", order.pk)
        self.assertEqual(response.status_code, 400)
        self.assertTrue(Order.objects.filter(pk=order.pk).exists())

    def test_product_in_orders_is_kept_and_unused_product_is_deleted(self):
        self.make_order()
        self.assertEqual(self.delete("products", self.product.pk).status_code, 400)
        unused = Product.objects.create(name="Gas", unit_price=Decimal("100"))
        self.assertEqual(self.delete("products", unused.pk).status_code, 200)
        self.assertFalse(Product.objects.filter(pk=unused.pk).exists())

    def test_vehicle_with_trips_is_kept(self):
        TripPlanner.plan_trip(self.vehicle, Order.objects.filter(pk=self.make_order().pk))
        self.assertEqual(self.delete("vehicles", self.vehicle.pk).status_code, 400)
        spare = Vehicle.objects.create(plate="P-2", model="Panel", capacity_kg=500, fuel_efficiency_km_l=9, cost_per_km=2)
        self.assertEqual(self.delete("vehicles", spare.pk).status_code, 200)

    def test_driver_with_user_account_is_kept(self):
        account = User.objects.create_user("repartidor")
        linked = Driver.objects.create(user=account, name="Con cuenta", license_number="L-1")
        response = self.delete("drivers", linked.pk)
        self.assertEqual(response.status_code, 400)
        self.assertIn("Usuarios", response.json()["error"])
        standalone = Driver.objects.create(name="Sin cuenta", license_number="L-2")
        self.assertEqual(self.delete("drivers", standalone.pk).status_code, 200)

    def test_department_in_use_is_kept_and_empty_department_is_deleted(self):
        self.assertEqual(self.delete("departments", self.department.pk).status_code, 400)
        empty = Department.objects.create(code="ESC", name="Escuintla")
        self.assertEqual(self.delete("departments", empty.pk).status_code, 200)
        self.assertFalse(Department.objects.filter(pk=empty.pk).exists())

    def test_seller_cannot_delete(self):
        self.user.profile.role = UserProfile.Role.SELLER
        self.user.profile.save()
        self.assertEqual(self.delete("stores", self.store.pk).status_code, 403)
        self.assertTrue(Store.objects.filter(pk=self.store.pk).exists())

    def test_unknown_kind_and_missing_record_return_404(self):
        self.assertEqual(self.delete("payments", 1).status_code, 404)
        self.assertEqual(self.delete("stores", 999999).status_code, 404)
