from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("logistics", "0013_order_departure_location"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="InventoryItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("quantity", models.PositiveIntegerField(default=0)),
                ("minimum_quantity", models.PositiveIntegerField(default=0)),
                ("product", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="inventory", to="logistics.product")),
                ("updated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="inventory_updates", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["product__product_type", "product__name"]},
        ),
        migrations.CreateModel(
            name="InventoryMovement",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("movement_type", models.CharField(choices=[("set", "Conteo fisico"), ("entry", "Entrada"), ("exit", "Salida")], max_length=10)),
                ("quantity", models.PositiveIntegerField()),
                ("previous_quantity", models.PositiveIntegerField()),
                ("resulting_quantity", models.PositiveIntegerField()),
                ("reason", models.CharField(max_length=240)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("inventory", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="movements", to="logistics.inventoryitem")),
                ("recorded_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="inventory_movements", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at", "-id"]},
        ),
    ]
