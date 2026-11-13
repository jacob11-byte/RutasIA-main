from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("logistics", "0014_inventoryitem_inventorymovement"),
    ]

    operations = [
        migrations.AddField(
            model_name="order",
            name="inventory_reserved",
            field=models.BooleanField(default=False),
        ),
    ]
