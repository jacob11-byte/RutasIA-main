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
