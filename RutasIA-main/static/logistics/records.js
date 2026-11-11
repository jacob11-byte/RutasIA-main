/* Permanent deletion of records without history. Requires connection so the server validates dependencies. */
const DELETE_LABELS = {
    stores: ["la tienda", "Tienda eliminada."],
    orders: ["el pedido", "Pedido eliminado."],
    products: ["el producto", "Producto eliminado."],
    vehicles: ["el vehiculo", "Vehiculo eliminado."],
    drivers: ["al repartidor", "Repartidor eliminado."],
    departments: ["la zona", "Zona eliminada."]
};

function deleteButton(kind, id, name) {
    // Local records (negative ids) are discarded from the pending panel instead.
    if (!["admin", "supervisor"].includes(state.currentUser?.role) || id <= 0) return "";
    return `<button type="button" class="btn-inline btn-danger" data-delete-kind="${kind}" data-delete-id="${id}" data-delete-name="${escapeHtml(name)}">Eliminar</button>`;
}

async function onDeleteRecordClick(event) {
    const button = event.target.closest("button[data-delete-kind]");
    if (!button) return;
    const { deleteKind: kind, deleteId: id, deleteName: name } = button.dataset;
    const [subject, done] = DELETE_LABELS[kind];
    if (!navigator.onLine) {
        showToast("Eliminar requiere conexion para validar que el registro no tenga historial.", true);
        return;
    }
    if (!confirm(`¿Eliminar ${subject} "${name}"? Esta accion no se puede deshacer.`)) return;
    button.disabled = true;
    try {
        await postJson(`/api/${kind}/${id}/delete/`, {}, makeLocalId());
        await reloadAll();
        showToast(done);
    } catch (error) {
        showToast(error.message, true);
        button.disabled = false;
    }
}

document.addEventListener("DOMContentLoaded", () => {
    document.addEventListener("click", onDeleteRecordClick);
});
