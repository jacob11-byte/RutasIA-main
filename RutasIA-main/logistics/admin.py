from django.contrib import admin
from .models import (
    Department,
    Order,
    OrderItem,
    Payment,
    Product,
    RouteConnection,
    RouteStop,
    Store,
    Trip,
    TripEvent,
    TripOrder,
    Vehicle,
)


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ("code", "name")
    search_fields = ("code", "name")


@admin.register(RouteConnection)
class RouteConnectionAdmin(admin.ModelAdmin):
    list_display = ("origin", "destination", "distance_km", "is_bidirectional")
    list_filter = ("is_bidirectional",)
    search_fields = ("origin__name", "destination__name")


@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display = ("plate", "model", "capacity_kg", "fuel_efficiency_km_l", "cost_per_km", "is_active")
    list_filter = ("is_active",)
    search_fields = ("plate", "model")


@admin.register(Store)
class StoreAdmin(admin.ModelAdmin):
    list_display = ("name", "municipality", "neighborhood", "department", "product_type", "phone", "is_active")
    list_filter = ("product_type", "is_active", "department", "municipality")
    search_fields = ("name", "contact_name", "phone", "municipality", "neighborhood", "address")


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "presentation", "product_type", "unit_price", "unit_weight_kg", "is_active")
    list_filter = ("product_type", "is_active")
    search_fields = ("name", "presentation")


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("code", "store", "origin", "destination", "weight_kg", "package_count", "priority", "status")
    list_filter = ("status", "priority")
    search_fields = ("code", "store__name")
    inlines = [OrderItemInline]


class TripOrderInline(admin.TabularInline):
    model = TripOrder
    extra = 0


class RouteStopInline(admin.TabularInline):
    model = RouteStop
    extra = 0


@admin.register(Trip)
class TripAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "vehicle",
        "origin",
        "destination",
        "total_distance_km",
        "estimated_cost",
        "status",
    )
    list_filter = ("status",)
    search_fields = ("code", "vehicle__plate")
    inlines = [TripOrderInline, RouteStopInline]


@admin.register(RouteStop)
class RouteStopAdmin(admin.ModelAdmin):
    list_display = ("trip", "sequence", "store", "order", "status", "delivered_at")
    list_filter = ("status",)
    search_fields = ("trip__code", "store__name", "order__code")


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("store", "order", "trip", "amount", "payment_type", "method", "sync_status", "created_at")
    list_filter = ("payment_type", "method", "sync_status")
    search_fields = ("store__name", "order__code", "trip__code", "uuid")


@admin.register(TripEvent)
class TripEventAdmin(admin.ModelAdmin):
    list_display = ("trip", "note", "created_at")
    search_fields = ("trip__code", "note")

# Register your models here.
