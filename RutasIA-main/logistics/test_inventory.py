import json
import uuid
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase

from logistics.models import (
    Department,
    InventoryItem,
    InventoryMovement,
    Order,
    OrderItem,
    Product,
    Store,
    UserProfile,
)


class InventoryApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("inventario", password="Credencial-Segura-2026!")
        UserProfile.objects.create(user=self.user, role=UserProfile.Role.ADMIN)
        self.client.force_login(self.user)
        self.water = Product.objects.create(
            name="Garrafon de agua",
            product_type=Product.Type.WATER,
            presentation="5 galones",
            unit_price=Decimal("20.00"),
            unit_weight_kg=Decimal("20.00"),
        )
        self.gas = Product.objects.create(
            name="Cilindro de gas",
            product_type=Product.Type.GAS,
            presentation="25 libras",
            unit_price=Decimal("125.00"),
            unit_weight_kg=Decimal("11.34"),
        )

    def post(self, url, payload):
        return self.client.post(
            url,
            json.dumps(payload),
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        )

    def adjust(self, product, movement_type, quantity, minimum=5, reason="Prueba de inventario"):
        return self.post("/api/inventory/", {
            "product_id": product.pk,
            "movement_type": movement_type,
            "quantity": quantity,
            "minimum_quantity": minimum,
            "reason": reason,
        })

    def test_inventory_supports_physical_count_entries_exits_and_summary(self):
        self.assertEqual(self.adjust(self.gas, "set", 20).status_code, 200)
        self.assertEqual(self.adjust(self.gas, "entry", 5).status_code, 200)
        self.assertEqual(self.adjust(self.gas, "exit", 3).status_code, 200)
        self.assertEqual(self.adjust(self.water, "set", 4).status_code, 200)

        gas_stock = InventoryItem.objects.get(product=self.gas)
        self.assertEqual(gas_stock.quantity, 22)
        self.assertEqual(gas_stock.updated_by, self.user)
        self.assertEqual(InventoryMovement.objects.filter(inventory=gas_stock).count(), 3)

        payload = self.client.get("/api/inventory/").json()
        self.assertEqual(payload["summary"], {"gas": 22, "water": 4, "low_stock": 1})
        self.assertEqual(payload["movements"][0]["resulting_quantity"], 4)

    def test_inventory_rejects_negative_stock_and_invalid_whole_quantities(self):
        self.assertEqual(self.adjust(self.gas, "set", 2).status_code, 200)
        response = self.adjust(self.gas, "exit", 3)
        self.assertEqual(response.status_code, 400)
        self.assertIn("solo hay 2", response.json()["error"])
        self.assertEqual(self.adjust(self.gas, "entry", 1.5).status_code, 400)
        self.assertEqual(InventoryItem.objects.get(product=self.gas).quantity, 2)

    def test_seller_can_read_inventory_but_cannot_adjust_it(self):
        self.user.profile.role = UserProfile.Role.SELLER
        self.user.profile.save()
        self.assertEqual(self.client.get("/api/inventory/").status_code, 200)
        self.assertEqual(self.adjust(self.water, "set", 10).status_code, 403)

    def test_product_price_can_change_without_rewriting_existing_sales(self):
        department = Department.objects.create(code="GUA-I", name="Guatemala inventario")
        store = Store.objects.create(name="Tienda", department=department, latitude=14.63, longitude=-90.51)
        order = Order.objects.create(store=store, origin=department, destination=department, weight_kg=20)
        item = OrderItem.objects.create(order=order, product=self.water, quantity=2, unit_price=self.water.unit_price)

        response = self.post(f"/api/products/{self.water.pk}/", {
            "name": self.water.name,
            "product_type": self.water.product_type,
            "presentation": self.water.presentation,
            "unit_price": "23.50",
            "unit_weight_kg": "20.00",
            "is_active": True,
        })
        self.assertEqual(response.status_code, 200)
        self.water.refresh_from_db()
        item.refresh_from_db()
        self.assertEqual(self.water.unit_price, Decimal("23.50"))
        self.assertEqual(item.unit_price, Decimal("20.00"))
        self.assertEqual(order.total_amount, Decimal("40.00"))

    def test_orders_require_stock_deduct_it_and_restore_it_when_canceled(self):
        department = Department.objects.create(code="GUA-S", name="Guatemala stock")
        store = Store.objects.create(name="Cliente stock", department=department, latitude=14.63, longitude=-90.51)
        InventoryItem.objects.create(product=self.water, quantity=2, minimum_quantity=1)
        payload = {
            "origin_id": department.pk,
            "store_id": store.pk,
            "items": [{"product_id": self.water.pk, "quantity": 3}],
        }
        rejected = self.post("/api/orders/", payload)
        self.assertEqual(rejected.status_code, 400)
        self.assertIn("Disponible: 2; solicitado: 3", rejected.json()["error"])
        self.assertFalse(Order.objects.filter(store=store).exists())

        payload["items"][0]["quantity"] = 2
        created = self.post("/api/orders/", payload)
        self.assertEqual(created.status_code, 201)
        order = Order.objects.get(pk=created.json()["order"]["id"])
        stock = InventoryItem.objects.get(product=self.water)
        self.assertEqual(stock.quantity, 0)
        self.assertTrue(order.inventory_reserved)

        canceled = self.post(f"/api/orders/{order.pk}/action/", {"action": "cancel"})
        self.assertEqual(canceled.status_code, 200)
        stock.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(stock.quantity, 2)
        self.assertFalse(order.inventory_reserved)
        self.assertEqual(
            list(InventoryMovement.objects.filter(inventory=stock).values_list("movement_type", flat=True)),
            [InventoryMovement.MovementType.ENTRY, InventoryMovement.MovementType.EXIT],
        )

    def test_deleting_a_pending_order_restores_reserved_stock(self):
        department = Department.objects.create(code="GUA-D", name="Guatemala delete stock")
        store = Store.objects.create(name="Cliente eliminar", department=department, latitude=14.63, longitude=-90.51)
        stock = InventoryItem.objects.create(product=self.gas, quantity=5)
        created = self.post("/api/orders/", {
            "origin_id": department.pk,
            "store_id": store.pk,
            "items": [{"product_id": self.gas.pk, "quantity": 2}],
        })
        order_id = created.json()["order"]["id"]
        stock.refresh_from_db()
        self.assertEqual(stock.quantity, 3)
        deleted = self.post(f"/api/orders/{order_id}/delete/", {})
        self.assertEqual(deleted.status_code, 200)
        stock.refresh_from_db()
        self.assertEqual(stock.quantity, 5)
