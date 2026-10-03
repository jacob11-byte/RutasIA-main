from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from logistics.models import Department, Driver, Order, OrderItem, Product, RouteConnection, Store, Vehicle


class Command(BaseCommand):
    help = "Carga datos de demostración para el sistema de rutas."

    @transaction.atomic
    def handle(self, *args, **options):
        departments_data = [
            ("GUA", "Guatemala", Decimal("14.634915"), Decimal("-90.506882")),
            ("SAC", "Sacatepéquez", Decimal("14.558571"), Decimal("-90.734306")),
            ("ESC", "Escuintla", Decimal("14.305000"), Decimal("-90.785000")),
            ("CHI", "Chimaltenango", Decimal("14.661111"), Decimal("-90.820000")),
            ("QUE", "Quetzaltenango", Decimal("14.845500"), Decimal("-91.518000")),
            ("RET", "Retalhuleu", Decimal("14.536111"), Decimal("-91.677778")),
            ("SUC", "Suchitepéquez", Decimal("14.534000"), Decimal("-91.363000")),
            ("PET", "Petén", Decimal("16.917000"), Decimal("-89.892000")),
            ("IZA", "Izabal", Decimal("15.728000"), Decimal("-88.594000")),
            ("ZAC", "Zacapa", Decimal("14.973000"), Decimal("-89.530000")),
        ]

        departments = {}
        for code, name, lat, lng in departments_data:
            department, _ = Department.objects.get_or_create(
                code=code,
                defaults={"name": name, "latitude": lat, "longitude": lng},
            )
            if department.name != name:
                department.name = name
                department.latitude = lat
                department.longitude = lng
                department.save(update_fields=["name", "latitude", "longitude"])
            departments[code] = department

        routes_data = [
            ("GUA", "SAC", Decimal("42.0")),
            ("GUA", "CHI", Decimal("55.0")),
            ("GUA", "ESC", Decimal("64.0")),
            ("SAC", "ESC", Decimal("52.0")),
            ("CHI", "QUE", Decimal("173.0")),
            ("ESC", "SUC", Decimal("101.0")),
            ("SUC", "RET", Decimal("47.0")),
            ("RET", "QUE", Decimal("62.0")),
            ("GUA", "ZAC", Decimal("147.0")),
            ("ZAC", "IZA", Decimal("98.0")),
            ("IZA", "PET", Decimal("304.0")),
            ("QUE", "PET", Decimal("402.0")),
            ("GUA", "PET", Decimal("506.0")),
        ]

        for origin_code, destination_code, distance in routes_data:
            RouteConnection.objects.get_or_create(
                origin=departments[origin_code],
                destination=departments[destination_code],
                defaults={"distance_km": distance, "is_bidirectional": True},
            )

        drivers_data = [
            ("Luis Ramirez - Ruta agua zona 7", "5521-3344", "REP-AGUA-01"),
            ("Maria Lopez - Ruta gas zona 11", "4433-2211", "REP-GAS-02"),
            ("Carlos Fuentes - Ruta mixta sur", "3399-8877", "REP-MIX-03"),
            ("Patricia Ruiz - Cobros pendientes", "5577-6612", "REP-COB-04"),
        ]

        drivers = {}
        for name, phone, license_number in drivers_data:
            driver, _ = Driver.objects.get_or_create(
                license_number=license_number,
                defaults={"name": name, "phone": phone, "is_active": True},
            )
            drivers[license_number] = driver

        vehicles_data = [
            ("AG-101", "Pickup reparto de garrafones", Decimal("1400"), Decimal("8.5"), Decimal("3.10"), "GUA", "REP-AGUA-01"),
            ("GAS-22", "Panel reparto de cilindros", Decimal("1800"), Decimal("7.2"), Decimal("3.80"), "GUA", "REP-GAS-02"),
            ("MIX-15", "Motocarro ruta mixta", Decimal("650"), Decimal("18.0"), Decimal("1.60"), "SAC", "REP-MIX-03"),
            ("COB-04", "Pickup apoyo cobros y entregas", Decimal("1200"), Decimal("9.4"), Decimal("2.90"), "ESC", "REP-COB-04"),
        ]

        for plate, model, capacity, efficiency, cost, current, license_number in vehicles_data:
            Vehicle.objects.get_or_create(
                plate=plate,
                defaults={
                    "model": model,
                    "capacity_kg": capacity,
                    "fuel_efficiency_km_l": efficiency,
                    "cost_per_km": cost,
                    "is_active": True,
                    "current_department": departments[current],
                    "driver": drivers[license_number],
                },
            )

        stores_data = [
            ("Tienda El Buen Precio", "Don Mario", "5544-1001", "Guatemala", "Bethania", "Colonia Bethania", "A la par de farmacia", Store.ProductType.WATER, "GUA", Decimal("14.650850"), Decimal("-90.554160")),
            ("Mini Market La Bendicion", "Ana Lopez", "5544-1002", "Guatemala", "Zona 11", "Zona 11", "Frente a parada de buses", Store.ProductType.GAS, "GUA", Decimal("14.602940"), Decimal("-90.545480")),
            ("Abarroteria El Camino", "Rosa Perez", "5544-1003", "Antigua Guatemala", "San Felipe", "Antigua Guatemala", "Porton azul", Store.ProductType.BOTH, "SAC", Decimal("14.558610"), Decimal("-90.733870")),
            ("Comercial El Sur", "Luis Garcia", "5544-1004", "Escuintla", "Centro", "Escuintla centro", "Esquina del mercado", Store.ProductType.WATER, "ESC", Decimal("14.305000"), Decimal("-90.785000")),
        ]

        stores = {}
        for name, contact, phone, municipality, neighborhood, address, reference, product_type, dept_code, lat, lng in stores_data:
            store, _ = Store.objects.get_or_create(
                name=name,
                defaults={
                    "contact_name": contact,
                    "phone": phone,
                    "municipality": municipality,
                    "neighborhood": neighborhood,
                    "address": address,
                    "reference": reference,
                    "product_type": product_type,
                    "department": departments[dept_code],
                    "latitude": lat,
                    "longitude": lng,
                    "is_active": True,
                },
            )
            stores[name] = store

        products_data = [
            ("Garrafon de agua", Product.Type.WATER, "5 galones", Decimal("18.00"), Decimal("20.00")),
            ("Pack agua pura", Product.Type.WATER, "24 botellas", Decimal("32.00"), Decimal("12.00")),
            ("Cilindro de gas", Product.Type.GAS, "25 libras", Decimal("135.00"), Decimal("11.34")),
            ("Cilindro de gas", Product.Type.GAS, "35 libras", Decimal("185.00"), Decimal("15.88")),
        ]
        products = {}
        for name, product_type, presentation, unit_price, unit_weight in products_data:
            product, _ = Product.objects.get_or_create(
                name=name,
                presentation=presentation,
                defaults={
                    "product_type": product_type,
                    "unit_price": unit_price,
                    "unit_weight_kg": unit_weight,
                    "is_active": True,
                },
            )
            products[(name, presentation)] = product

        if Order.objects.count() == 0:
            order_data = [
                ("GUA", "Tienda El Buen Precio", Order.Priority.HIGH, [(("Garrafon de agua", "5 galones"), 12), (("Pack agua pura", "24 botellas"), 4)]),
                ("GUA", "Mini Market La Bendicion", Order.Priority.NORMAL, [(("Cilindro de gas", "25 libras"), 4)]),
                ("GUA", "Abarroteria El Camino", Order.Priority.HIGH, [(("Garrafon de agua", "5 galones"), 8), (("Cilindro de gas", "35 libras"), 2)]),
                ("ESC", "Comercial El Sur", Order.Priority.NORMAL, [(("Pack agua pura", "24 botellas"), 10)]),
            ]
            for origin_code, store_name, priority, item_defs in order_data:
                store = stores[store_name]
                total_weight = Decimal("0.00")
                total_packages = 0
                order = Order.objects.create(
                    origin=departments[origin_code],
                    destination=store.department,
                    store=store,
                    weight_kg=Decimal("1.00"),
                    package_count=1,
                    priority=priority,
                    status=Order.Status.PENDING,
                )
                for product_key, quantity in item_defs:
                    product = products[product_key]
                    OrderItem.objects.create(
                        order=order,
                        product=product,
                        quantity=quantity,
                        unit_price=product.unit_price,
                    )
                    total_weight += Decimal(quantity) * product.unit_weight_kg
                    total_packages += quantity
                order.weight_kg = total_weight
                order.package_count = total_packages
                order.save(update_fields=["weight_kg", "package_count", "updated_at"])

        fallback_product = products[("Garrafon de agua", "5 galones")]
        for order in Order.objects.filter(items__isnull=True):
            OrderItem.objects.create(
                order=order,
                product=fallback_product,
                quantity=order.package_count or 1,
                unit_price=fallback_product.unit_price,
            )

        self.stdout.write(self.style.SUCCESS("Datos de demostración cargados correctamente."))
