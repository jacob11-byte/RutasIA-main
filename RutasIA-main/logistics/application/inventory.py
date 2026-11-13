from collections import defaultdict

from django.contrib.auth.models import User

from logistics.domain.exceptions import PlanningError
from logistics.models import InventoryItem, InventoryMovement, Order


def _order_quantities(order: Order) -> tuple[dict[int, int], dict[int, str]]:
    quantities: dict[int, int] = defaultdict(int)
    names: dict[int, str] = {}
    for line in order.items.select_related("product").all():
        quantities[line.product_id] += line.quantity
        names[line.product_id] = str(line.product)
    return dict(quantities), names


def reserve_order_inventory(order: Order, *, recorded_by: User | None) -> None:
    """Deduct available units atomically when an order is accepted."""
    quantities, names = _order_quantities(order)
    inventory = {
        item.product_id: item
        for item in InventoryItem.objects.select_for_update().filter(product_id__in=sorted(quantities))
    }
    for product_id, quantity in quantities.items():
        item = inventory.get(product_id)
        available = item.quantity if item else 0
        if available < quantity:
            raise PlanningError(
                f"Inventario insuficiente para {names[product_id]}. "
                f"Disponible: {available}; solicitado: {quantity}."
            )

    for product_id, quantity in quantities.items():
        item = inventory[product_id]
        previous = item.quantity
        item.quantity -= quantity
        item.updated_by = recorded_by
        item.save(update_fields=["quantity", "updated_by", "updated_at"])
        InventoryMovement.objects.create(
            inventory=item,
            movement_type=InventoryMovement.MovementType.EXIT,
            quantity=quantity,
            previous_quantity=previous,
            resulting_quantity=item.quantity,
            reason=f"Reserva automatica del pedido {order.code}",
            recorded_by=recorded_by,
        )
    order.inventory_reserved = True
    order.save(update_fields=["inventory_reserved", "updated_at"])


def restore_order_inventory(order: Order, *, recorded_by: User | None, reason: str) -> None:
    """Return units once when a reserved order is canceled or deleted."""
    if not order.inventory_reserved:
        return
    quantities, names = _order_quantities(order)
    inventory = {
        item.product_id: item
        for item in InventoryItem.objects.select_for_update().filter(product_id__in=sorted(quantities))
    }
    for product_id, quantity in quantities.items():
        item = inventory.get(product_id)
        if item is None:
            raise PlanningError(f"No existe inventario para devolver {names[product_id]}.")
        previous = item.quantity
        item.quantity += quantity
        item.updated_by = recorded_by
        item.save(update_fields=["quantity", "updated_by", "updated_at"])
        InventoryMovement.objects.create(
            inventory=item,
            movement_type=InventoryMovement.MovementType.ENTRY,
            quantity=quantity,
            previous_quantity=previous,
            resulting_quantity=item.quantity,
            reason=reason,
            recorded_by=recorded_by,
        )
    order.inventory_reserved = False
    order.save(update_fields=["inventory_reserved", "updated_at"])
