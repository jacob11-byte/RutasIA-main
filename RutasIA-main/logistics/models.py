from __future__ import annotations

import random
import string
import uuid
from decimal import Decimal
from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone


def _random_suffix(length: int = 4) -> str:
    return "".join(random.choices(string.digits, k=length))


class TimestampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class FuelPrice(TimestampedModel):
    """Singleton — precio de combustible en GTQ/galón. Usar FuelPrice.current()."""
    regular_gtq_gal = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal("29.50"))
    super_gtq_gal = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal("32.00"))
    diesel_gtq_gal = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal("24.00"))
    source = models.CharField(max_length=120, default="MEM Guatemala")

    class Meta:
        verbose_name = "Precio de combustible"

    def __str__(self) -> str:
        return f"Regular Q{self.regular_gtq_gal}/gal — {self.updated_at:%d/%m/%Y %H:%M}"

    @classmethod
    def current(cls) -> "FuelPrice":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class UserProfile(models.Model):
    class Role(models.TextChoices):
        ADMIN = "admin", "Administrador"
        SUPERVISOR = "supervisor", "Supervisor"
        OPERATOR = "operator", "Operador"

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.OPERATOR)

    def __str__(self) -> str:
        return f"{self.user.username} ({self.get_role_display()})"


class Department(models.Model):
    code = models.CharField(max_length=8, unique=True)
    name = models.CharField(max_length=80, unique=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"


class RouteConnection(TimestampedModel):
    origin = models.ForeignKey(
        Department,
        on_delete=models.CASCADE,
        related_name="connections_from",
    )
    destination = models.ForeignKey(
        Department,
        on_delete=models.CASCADE,
        related_name="connections_to",
    )
    distance_km = models.DecimalField(max_digits=8, decimal_places=2)
    is_bidirectional = models.BooleanField(default=True)

    class Meta:
        ordering = ["origin__name", "destination__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["origin", "destination"],
                name="uniq_route_connection_direction",
            ),
            models.CheckConstraint(
                condition=~models.Q(origin=models.F("destination")),
                name="origin_destination_must_differ",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.origin.name} -> {self.destination.name} ({self.distance_km} km)"


class Driver(TimestampedModel):
    name = models.CharField(max_length=120)
    phone = models.CharField(max_length=20, blank=True)
    license_number = models.CharField(max_length=30, unique=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.license_number})"


class Vehicle(TimestampedModel):
    plate = models.CharField(max_length=16, unique=True)
    model = models.CharField(max_length=100)
    capacity_kg = models.DecimalField(max_digits=8, decimal_places=2)
    fuel_efficiency_km_l = models.DecimalField(max_digits=8, decimal_places=2)
    cost_per_km = models.DecimalField(max_digits=8, decimal_places=2)
    is_active = models.BooleanField(default=True)
    current_department = models.ForeignKey(
        Department,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="vehicles",
    )
    driver = models.ForeignKey(
        Driver,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="vehicles",
    )

    class Meta:
        ordering = ["plate"]

    def __str__(self) -> str:
        return f"{self.plate} - {self.model}"


class Store(TimestampedModel):
    class ProductType(models.TextChoices):
        WATER = "water", "Agua purificada"
        GAS = "gas", "Gas"
        BOTH = "both", "Agua y gas"

    name = models.CharField(max_length=140)
    contact_name = models.CharField(max_length=120, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    municipality = models.CharField(max_length=120, blank=True)
    neighborhood = models.CharField(max_length=140, blank=True)
    address = models.CharField(max_length=220, blank=True)
    reference = models.CharField(max_length=220, blank=True)
    product_type = models.CharField(max_length=12, choices=ProductType.choices, default=ProductType.WATER)
    department = models.ForeignKey(Department, on_delete=models.PROTECT, related_name="stores")
    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.department.code})"


class Product(TimestampedModel):
    class Type(models.TextChoices):
        WATER = "water", "Agua purificada"
        GAS = "gas", "Gas"

    name = models.CharField(max_length=120)
    product_type = models.CharField(max_length=12, choices=Type.choices, default=Type.WATER)
    presentation = models.CharField(max_length=80, blank=True)
    unit_price = models.DecimalField(max_digits=8, decimal_places=2)
    unit_weight_kg = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal("1.00"))
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["product_type", "name"]

    def __str__(self) -> str:
        label = f" - {self.presentation}" if self.presentation else ""
        return f"{self.name}{label}"


class Order(TimestampedModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pendiente"
        ASSIGNED = "assigned", "Asignado"
        IN_TRANSIT = "in_transit", "En tránsito"
        DELIVERED = "delivered", "Entregado"
        CANCELED = "canceled", "Cancelado"

    class Priority(models.TextChoices):
        LOW = "low", "Baja"
        NORMAL = "normal", "Normal"
        HIGH = "high", "Alta"

    code = models.CharField(max_length=24, unique=True, blank=True)
    origin = models.ForeignKey(Department, on_delete=models.PROTECT, related_name="orders_origin")
    destination = models.ForeignKey(
        Department,
        on_delete=models.PROTECT,
        related_name="orders_destination",
    )
    store = models.ForeignKey(
        Store,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="orders",
    )
    weight_kg = models.DecimalField(max_digits=8, decimal_places=2)
    package_count = models.PositiveIntegerField(default=1)
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.NORMAL)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    requested_for = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if not self.code:
            stamp = timezone.now().strftime("%Y%m%d")
            self.code = f"PED-{stamp}-{_random_suffix()}"
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.code} ({self.origin.code}->{self.destination.code})"

    @property
    def total_amount(self) -> Decimal:
        total = sum((item.subtotal for item in self.items.all()), Decimal("0.00"))
        return total.quantize(Decimal("0.01"))

    @property
    def paid_amount(self) -> Decimal:
        total = sum((payment.amount for payment in self.payments.all()), Decimal("0.00"))
        return total.quantize(Decimal("0.01"))

    @property
    def balance_due(self) -> Decimal:
        return max(self.total_amount - self.paid_amount, Decimal("0.00")).quantize(Decimal("0.01"))


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="order_items")
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=8, decimal_places=2)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, blank=True)

    class Meta:
        ordering = ["id"]

    def save(self, *args, **kwargs):
        self.subtotal = (Decimal(self.quantity) * Decimal(self.unit_price)).quantize(Decimal("0.01"))
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.quantity} x {self.product}"


class Trip(TimestampedModel):
    class Status(models.TextChoices):
        PLANNED = "planned", "Planificado"
        IN_PROGRESS = "in_progress", "En progreso"
        COMPLETED = "completed", "Completado"
        CANCELED = "canceled", "Cancelado"

    code = models.CharField(max_length=24, unique=True, blank=True)
    vehicle = models.ForeignKey(Vehicle, on_delete=models.PROTECT, related_name="trips")
    driver = models.ForeignKey(
        Driver,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="trips",
    )
    origin = models.ForeignKey(Department, on_delete=models.PROTECT, related_name="trips_origin")
    destination = models.ForeignKey(
        Department,
        on_delete=models.PROTECT,
        related_name="trips_destination",
    )
    orders = models.ManyToManyField(Order, through="TripOrder", related_name="trips")
    route_nodes = models.JSONField(default=list)
    total_distance_km = models.DecimalField(max_digits=9, decimal_places=2)
    estimated_fuel_gallons = models.DecimalField(max_digits=9, decimal_places=2)
    fuel_price_gtq_gal = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    estimated_fuel_cost_gtq = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    estimated_cost = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PLANNED)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if not self.code:
            stamp = timezone.now().strftime("%Y%m%d")
            self.code = f"VIA-{stamp}-{_random_suffix()}"
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.code} ({self.origin.code}->{self.destination.code})"


class TripOrder(models.Model):
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE)
    order = models.ForeignKey(Order, on_delete=models.CASCADE)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["trip", "order"], name="uniq_trip_order"),
        ]

    def __str__(self) -> str:
        return f"{self.trip.code} - {self.order.code}"


class RouteStop(TimestampedModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pendiente"
        DELIVERED = "delivered", "Entregado"
        NOT_DELIVERED = "not_delivered", "No entregado"

    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name="stops")
    order = models.ForeignKey(Order, on_delete=models.SET_NULL, null=True, blank=True, related_name="route_stops")
    store = models.ForeignKey(Store, on_delete=models.SET_NULL, null=True, blank=True, related_name="route_stops")
    sequence = models.PositiveIntegerField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    observation = models.CharField(max_length=240, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["trip", "sequence"]
        constraints = [
            models.UniqueConstraint(fields=["trip", "sequence"], name="uniq_trip_stop_sequence"),
        ]

    def __str__(self) -> str:
        target = self.store.name if self.store else (self.order.code if self.order else "Parada")
        return f"{self.trip.code} #{self.sequence} - {target}"


class Payment(TimestampedModel):
    class PaymentType(models.TextChoices):
        FULL = "full_payment", "Pago completo"
        PARTIAL = "partial_payment", "Abono"
        CREDIT = "credit", "Credito"

    class Method(models.TextChoices):
        CASH = "cash", "Efectivo"
        TRANSFER = "transfer", "Transferencia"
        OTHER = "other", "Otro"

    class SyncStatus(models.TextChoices):
        SYNCED = "synced", "Sincronizado"
        PENDING = "pending", "Pendiente"

    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    store = models.ForeignKey(Store, on_delete=models.PROTECT, related_name="payments")
    order = models.ForeignKey(Order, on_delete=models.SET_NULL, null=True, blank=True, related_name="payments")
    trip = models.ForeignKey(Trip, on_delete=models.SET_NULL, null=True, blank=True, related_name="payments")
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    payment_type = models.CharField(max_length=18, choices=PaymentType.choices, default=PaymentType.PARTIAL)
    method = models.CharField(max_length=12, choices=Method.choices, default=Method.CASH)
    sync_status = models.CharField(max_length=12, choices=SyncStatus.choices, default=SyncStatus.SYNCED)
    note = models.CharField(max_length=240, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.store.name} Q{self.amount}"


class TripEvent(TimestampedModel):
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name="events")
    note = models.TextField()

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.trip.code}: {self.note[:50]}"
