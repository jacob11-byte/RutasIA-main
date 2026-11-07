/* Customer history and collection controls; independent of map rendering. */
function paymentStatusLabel(order) {
    if (order.status === "canceled") return "Cancelado";
    return order.total_amount > 0 && order.balance_due <= 0 ? "Pagado" : order.paid_amount > 0 ? "Abonado" : "Pendiente de cobro";
}

function businessDate(value) {
    return value ? new Date(value).toLocaleString("es-GT") : "No registrada";
}

function renderCustomerHistory() {
    const select = document.getElementById("customer-history-select");
    const storeId = Number(select.value);
    const box = document.getElementById("customer-history");
    if (!storeId) { box.textContent = "Selecciona un cliente para consultar sus pedidos, entregas, cobros y observaciones."; return; }
    const orders = state.orders.filter(order => order.store_id === storeId);
    const payments = state.payments.filter(payment => payment.store_id === storeId);
    const sales = orders.filter(order => order.status !== "canceled").reduce((sum, order) => sum + order.total_amount, 0);
    const collected = payments.filter(payment => payment.payment_type !== "credit").reduce((sum, payment) => sum + Number(payment.amount), 0);
    const orderRows = orders.map(order => `<tr><td>${escapeHtml(order.code)}</td><td>${escapeHtml(businessDate(order.requested_for))}</td>
        <td>${escapeHtml(order.items.map(item => `${item.quantity} x ${item.product_name}`).join(", "))}</td>
        <td>${escapeHtml(statusLabel(order.status))}</td><td>${paymentStatusLabel(order)}</td>
        <td>Q ${Number(order.total_amount).toFixed(2)}</td><td>Q ${Number(order.balance_due).toFixed(2)}</td></tr>`).join("");
    const paymentRows = payments.map(payment => `<tr><td>${escapeHtml(businessDate(payment.occurred_at || payment.created_at))}</td>
        <td>${escapeHtml(payment.order_code || "Aplicado a los pedidos mas antiguos")}</td><td>${escapeHtml(paymentTypeLabel(payment.payment_type))}</td>
        <td>Q ${Number(payment.amount).toFixed(2)}</td><td>${escapeHtml(payment.recorded_by_name || "No registrado (historico)")}</td>
        <td>${escapeHtml(payment.driver_name || "Caja / sin repartidor registrado")}</td><td>${escapeHtml(payment.note || "-")}</td>
        <td>${escapeHtml(payment.sync_status)}</td></tr>`).join("");
    const visits = state.trips.flatMap(trip => trip.stops.filter(stop => stop.store_id === storeId).map(stop => ({ trip, stop })));
    const visitRows = visits.map(({ trip, stop }) => {
        const event = trip.events.find(event => event.stop_id === stop.id);
        return `<tr><td>${escapeHtml(trip.code)}</td><td>${stop.sequence}</td><td>${escapeHtml(trip.driver_name || "No asignado")}</td>
            <td>${escapeHtml(statusLabel(stop.status))}</td><td>${escapeHtml(businessDate(stop.delivered_at || event?.occurred_at))}</td>
            <td>${escapeHtml(event?.recorded_by_name || "No registrado (historico)")}</td><td>${escapeHtml(stop.observation || "-")}</td></tr>`;
    }).join("");
    box.innerHTML = `<p>Ventas: <strong>Q ${sales.toFixed(2)}</strong> · Recibido: <strong>Q ${collected.toFixed(2)}</strong> · Saldo: <strong>Q ${Math.max(0, sales - collected).toFixed(2)}</strong></p>
        <h4>Pedidos y cuentas pendientes</h4><table><thead><tr><th>Pedido</th><th>Fecha</th><th>Productos</th><th>Entrega</th><th>Cobro</th><th>Total</th><th>Saldo</th></tr></thead><tbody>${orderRows || '<tr><td colspan="7">Sin pedidos.</td></tr>'}</tbody></table>
        <h4>Cobros y abonos</h4><table><thead><tr><th>Fecha de operacion</th><th>Pedido</th><th>Tipo</th><th>Recibido</th><th>Registrado por</th><th>Repartidor</th><th>Nota</th><th>Sincronizacion</th></tr></thead><tbody>${paymentRows || '<tr><td colspan="8">Sin cobros.</td></tr>'}</tbody></table>
        <h4>Visitas y observaciones</h4><table><thead><tr><th>Ruta</th><th>Parada</th><th>Repartidor</th><th>Resultado</th><th>Fecha</th><th>Registrado por</th><th>Observacion</th></tr></thead><tbody>${visitRows || '<tr><td colspan="7">Sin visitas asignadas.</td></tr>'}</tbody></table>`;
}

function updatePaymentRules() {
    const form = document.getElementById("payment-form");
    const kind = form.payment_type.value;
    const order = state.orders.find(row => row.id === Number(form.order_id.value));
    const balance = order ? order.balance_due : state.orders.filter(row => row.store_id === Number(form.store_id.value) && row.status !== "canceled").reduce((sum, row) => sum + row.balance_due, 0);
    form.amount.readOnly = kind !== "partial_payment";
    form.amount.min = kind === "credit" ? "0" : "0.01";
    form.amount.max = String(balance);
    form.order_id.required = kind === "credit";
    if (kind === "credit") form.amount.value = "0.00";
    if (kind === "full_payment") form.amount.value = balance.toFixed(2);
    if (kind === "partial_payment" && Number(form.amount.value) === 0) form.amount.value = "";
    document.getElementById("payment-help").textContent = kind === "credit"
        ? "Credito: selecciona el pedido. Se conserva su saldo pendiente y se registra Q 0.00 recibido."
        : `Saldo disponible: Q ${balance.toFixed(2)}. Un cobro sin pedido se aplica a las deudas mas antiguas del cliente. Transferencia registra un pago recibido; no procesa operaciones bancarias.`;
}

function selectAccessUser() {
    const form = document.getElementById("user-access-form");
    const user = state.users.find(row => row.id === Number(form.user_id.value));
    if (user) { form.role.value = user.role; form.is_active.checked = user.is_active; }
}

function renderBusinessDetails() {
    const history = document.getElementById("customer-history-select");
    const previous = history.value;
    history.innerHTML = '<option value="">Selecciona un cliente</option>' + state.stores.map(store => `<option value="${store.id}">${escapeHtml(store.name)}</option>`).join("");
    history.value = previous;
    renderCustomerHistory();
    const driver = document.getElementById("payment-driver");
    const previousDriver = driver.value;
    driver.innerHTML = '<option value="">Cobro en caja / sin repartidor</option>' + state.drivers.filter(driver => driver.is_active).map(driver => `<option value="${driver.id}">${escapeHtml(driver.name)}</option>`).join("");
    driver.value = previousDriver;
    const access = document.getElementById("access-user");
    const previousUser = access.value;
    access.innerHTML = '<option value="">Selecciona un usuario</option>' + state.users.map(user => `<option value="${user.id}">${escapeHtml(user.username)}</option>`).join("");
    access.value = previousUser;
    selectAccessUser();
    updatePaymentRules();
}

document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("customer-history-select").addEventListener("change", renderCustomerHistory);
    document.getElementById("access-user").addEventListener("change", selectAccessUser);
    const payment = document.getElementById("payment-form");
    for (const name of ["store_id", "order_id", "payment_type"]) payment.elements[name].addEventListener("change", () => queueMicrotask(updatePaymentRules));
    payment.addEventListener("reset", () => queueMicrotask(updatePaymentRules));
    document.getElementById("orders-body").addEventListener("click", async event => {
        const button = event.target.closest("[data-cancel-order]");
        if (!button || !confirm("¿Cancelar este pedido pendiente? No se cancelan pedidos con cobros ni entregas confirmadas.")) return;
        button.disabled = true;
        try {
            const result = await postJsonOrQueue(`/api/orders/${button.dataset.cancelOrder}/action/`, { action: "cancel" }, "Cancelar pedido");
            showToast(result.queued ? "Cancelacion guardada; pendiente de sincronizar." : "Pedido cancelado.");
        } catch (error) { showToast(error.message, true); }
        finally { button.disabled = false; }
    });
    bindSafeSubmit("user-access-form", async event => {
        const form = event.currentTarget;
        if (!navigator.onLine) { showToast("La administracion de accesos requiere conexion.", true); return; }
        try {
            await postJson(`/api/users/${form.user_id.value}/`, { role: form.role.value, is_active: form.is_active.checked }, makeLocalId());
            state.users = (await getJson(API.users)).users;
            renderUsers(); renderBusinessDetails();
            showToast("Rol y acceso actualizados.");
        } catch (error) { showToast(error.message, true); }
    });
});
