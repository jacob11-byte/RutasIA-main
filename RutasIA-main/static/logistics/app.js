const API = {
    me: "/api/me/",
    users: "/api/users/",
    dashboard: "/api/dashboard/",
    departments: "/api/departments/",
    connections: "/api/connections/",
    drivers: "/api/drivers/",
    stores: "/api/stores/",
    products: "/api/products/",
    vehicles: "/api/vehicles/",
    orders: "/api/orders/",
    trips: "/api/trips/",
    planTrip: "/api/trips/plan/",
    payments: "/api/payments/",
    balances: "/api/balances/",
    reports: "/api/reports/",
    fuelPrice: "/api/fuel-price/"
};

const OFFLINE_QUEUE_KEY = "flamia.offlineQueue.v1"; // Legacy queue is preserved for manual recovery.
let offlinePendingCount = 0;
let offlineLastError = "";
let offlineRetryTimer;

const GUATEMALA_DEPARTMENTS = [
    { code: "GT01", name: "Guatemala",        lat: 14.634915, lng: -90.506882 },
    { code: "GT02", name: "El Progreso",      lat: 14.866600, lng: -90.070300 },
    { code: "GT03", name: "Sacatepéquez",     lat: 14.560100, lng: -90.733700 },
    { code: "GT04", name: "Chimaltenango",    lat: 14.659800, lng: -90.818600 },
    { code: "GT05", name: "Escuintla",        lat: 14.304900, lng: -90.784300 },
    { code: "GT06", name: "Santa Rosa",       lat: 14.279400, lng: -90.297700 },
    { code: "GT07", name: "Sololá",           lat: 14.776700, lng: -91.182600 },
    { code: "GT08", name: "Totonicapán",      lat: 14.909300, lng: -91.360600 },
    { code: "GT09", name: "Quetzaltenango",   lat: 14.845900, lng: -91.518300 },
    { code: "GT10", name: "Suchitepéquez",    lat: 14.532400, lng: -91.502400 },
    { code: "GT11", name: "Retalhuleu",       lat: 14.536800, lng: -91.686400 },
    { code: "GT12", name: "San Marcos",       lat: 14.963700, lng: -91.796000 },
    { code: "GT13", name: "Huehuetenango",    lat: 15.319200, lng: -91.469400 },
    { code: "GT14", name: "Quiché",           lat: 15.032600, lng: -91.149800 },
    { code: "GT15", name: "Baja Verapaz",     lat: 15.101900, lng: -90.315400 },
    { code: "GT16", name: "Alta Verapaz",     lat: 15.469700, lng: -90.368900 },
    { code: "GT17", name: "Petén",            lat: 16.927000, lng: -89.894800 },
    { code: "GT18", name: "Izabal",           lat: 15.729100, lng: -88.593300 },
    { code: "GT19", name: "Zacapa",           lat: 14.972400, lng: -89.524700 },
    { code: "GT20", name: "Chiquimula",       lat: 14.799700, lng: -89.546300 },
    { code: "GT21", name: "Jalapa",           lat: 14.633800, lng: -89.983100 },
    { code: "GT22", name: "Jutiapa",          lat: 14.291900, lng: -89.898000 },
];

const state = {
    currentUser: null,
    dashboard: null,
    departments: [],
    connections: [],
    drivers: [],
    stores: [],
    products: [],
    vehicles: [],
    orders: [],
    trips: [],
    payments: [],
    balances: [],
    report: null,
    users: []
};

let map = null;
let directionsRenderer = null;
let mapHasAutoFit = false;
let activeInfoWindow = null;
let selectedMapTripId = null;
let gmapMarkers = [];
let gmapStoreMarkers = [];
let gmapConnections = [];
let gmapRouteMarkers = [];
let gpsSimTimer = null;
let gpsSimMarker = null;
let lastDirectionsResult = null;
let deliverySimTimer = null;
let isSyncingOfflineQueue = false;
let editingStoreId = null;

document.addEventListener("DOMContentLoaded", async () => {
    initPwa();
    initDeliveryLocation();
    bindOfflineSync();
    bindTabs();
    initDeptPresetSelect();
    bindForms();
    bindFilters();
    await refreshOfflineSummary();
    await reloadAll();
    activateInitialTabFromUrl();
    renderOfflineStatus();
    if (navigator.onLine) syncPendingData();
});

function bindTabs() {
    const tabs = Array.from(document.querySelectorAll(".tab"));
    tabs.forEach((tab) => {
        tab.addEventListener("click", () => {
            tabs.forEach((x) => x.classList.remove("is-active"));
            tab.classList.add("is-active");
            const target = tab.dataset.tab;
            document.querySelectorAll(".panel").forEach((panel) => {
                panel.classList.toggle("is-active", panel.id === `tab-${target}`);
            });
            if (target === "map") {
                window.setTimeout(() => {
                    if (map) google.maps.event.trigger(map, "resize");
                }, 80);
            }
        });
    });
}

function bindSafeSubmit(id, handler) {
    const form = document.getElementById(id);
    form.addEventListener("submit", async event => {
        event.preventDefault();
        if (form.dataset.saving) return;
        form.dataset.saving = "true";
        const buttons = form.querySelectorAll('[type="submit"]');
        buttons.forEach(button => button.disabled = true);
        try { await handler(event); }
        finally {
            delete form.dataset.saving;
            buttons.forEach(button => button.disabled = false);
        }
    });
}

function bindForms() {
    document.getElementById("vehicle-form").addEventListener("submit", onVehicleSubmit);
    bindSafeSubmit("store-form", onStoreSubmit);
    document.getElementById("btn-store-gps").addEventListener("click", fillStoreGpsFromDevice);
    document.getElementById("btn-cancel-store-edit").addEventListener("click", cancelStoreEdit);
    document.getElementById("order-store").addEventListener("change", onOrderStoreChange);
    document.getElementById("order-product").addEventListener("change", updateOrderEstimate);
    document.querySelector("#order-form input[name='quantity']").addEventListener("input", updateOrderEstimate);
    document.getElementById("driver-form").addEventListener("submit", onDriverSubmit);
    document.getElementById("product-form").addEventListener("submit", onProductSubmit);
    bindSafeSubmit("order-form", onOrderSubmit);
    document.getElementById("payment-store").addEventListener("change", renderPaymentOrderSelect);
    bindSafeSubmit("payment-form", onPaymentSubmit);
    document.getElementById("planner-form").addEventListener("submit", onPlannerSubmit);
    bindSafeSubmit("event-form", onEventSubmit);
    document.getElementById("trips-body").addEventListener("click", onTripsActionClick);
    document.getElementById("stores-body").addEventListener("click", onStoresActionClick);
    document.getElementById("users-body").addEventListener("click", onUserApprovalClick);
    document.getElementById("pending-users-body").addEventListener("click", onUserApprovalClick);
    document.getElementById("user-form").addEventListener("submit", onUserSubmit);
    document.getElementById("department-form").addEventListener("submit", onDepartmentSubmit);
    document.getElementById("map-trip-select").addEventListener("change", onMapTripSelect);
    document.getElementById("map-route-summary").addEventListener("click", onRouteStopAction);
    document.getElementById("dept-preset-select").addEventListener("change", onDeptPresetChange);
    document.getElementById("btn-start-gps").addEventListener("click", startGpsSimulation);
    document.getElementById("btn-stop-gps").addEventListener("click", stopGpsSimulation);
    document.getElementById("btn-sim-delivery").addEventListener("click", () => {
        simulateDelivery(selectedMapTripId);
    });
    document.getElementById("fuel-form").addEventListener("submit", onFuelPriceSubmit);
    document.getElementById("btn-edit-fuel").addEventListener("click", () => {
        document.getElementById("fuel-form").style.display = "";
        document.getElementById("btn-edit-fuel").style.display = "none";
    });
    document.getElementById("btn-cancel-fuel").addEventListener("click", () => {
        document.getElementById("fuel-form").style.display = "none";
        document.getElementById("btn-edit-fuel").style.display = "";
    });
    document.getElementById("report-filter-btn").addEventListener("click", reloadReport);
    document.getElementById("btn-sync-now").addEventListener("click", syncPendingData);
}

function initPwa() {
    if (!("serviceWorker" in navigator)) return;
    navigator.serviceWorker.addEventListener("message", event => {
        if (event.data?.type === "FLAMIA_SESSION_ENDED") window.location.replace("/accounts/login/");
    });
    window.addEventListener("load", () => {
        navigator.serviceWorker.register("/service-worker.js").then(async () => {
            await navigator.serviceWorker.ready;
            // The first navigation happened before the worker controlled this page.
            const shell = await fetch("/", { credentials: "same-origin", cache: "no-store" });
            if (shell.ok && shell.headers.get("X-Flamia-User-ID") === FlamiaOffline.owner) {
                const cache = await caches.open("flamia-shell-v8");
                await cache.put("/", shell);
            }
        }).catch((error) => {
            offlineLastError = "No se pudo preparar la apertura offline. Abre Flamia con conexion y vuelve a intentarlo.";
            renderOfflineStatus();
            console.warn("No se pudo registrar el service worker:", error);
        });
    });
}

function bindOfflineSync() {
    window.addEventListener("online", () => {
        renderOfflineStatus();
        syncPendingData();
    });
    window.addEventListener("offline", () => renderOfflineStatus());
    window.addEventListener("focus", () => { if (navigator.onLine) syncPendingData(); });
    document.addEventListener("visibilitychange", () => {
        if (!document.hidden && navigator.onLine) syncPendingData();
    });
    offlineRetryTimer = window.setInterval(() => {
        if (navigator.onLine && offlinePendingCount) syncPendingData();
    }, 30000);
}

function activateInitialTabFromUrl() {
    const params = new URLSearchParams(window.location.search);
    const tab = params.get("tab");
    if (!tab) return;
    const tabButton = Array.from(document.querySelectorAll(".tab")).find((item) => item.dataset.tab === tab);
    tabButton?.click();
}


// â”€â”€ PRECIO DE GASOLINA â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

async function reloadFuelPrice() {
    try {
        const res = await getJson(API.fuelPrice);
        renderFuelPrice(res.fuel_price);
    } catch (_) {}
}

function renderFuelPrice(fp) {
    if (!fp) return;
    document.getElementById("fuel-regular").textContent = `Q ${fp.regular_gtq_gal.toFixed(2)}/gal`;
    document.getElementById("fuel-super").textContent = `Q ${fp.super_gtq_gal.toFixed(2)}/gal`;
    document.getElementById("fuel-diesel").textContent = `Q ${fp.diesel_gtq_gal.toFixed(2)}/gal`;
    const d = new Date(fp.updated_at);
    document.getElementById("fuel-updated-at").textContent =
        `${fp.source} · actualizado ${d.toLocaleDateString("es-GT")} ${d.toLocaleTimeString("es-GT", { hour: "2-digit", minute: "2-digit" })}`;
    const isAdmin = state.currentUser && state.currentUser.role === "admin";
    document.getElementById("btn-edit-fuel").style.display = isAdmin ? "" : "none";
    const form = document.getElementById("fuel-form");
    form.regular_gtq_gal.value = fp.regular_gtq_gal.toFixed(2);
    form.super_gtq_gal.value = fp.super_gtq_gal.toFixed(2);
    form.diesel_gtq_gal.value = fp.diesel_gtq_gal.toFixed(2);
    form.source.value = fp.source;
}

async function onFuelPriceSubmit(event) {
    event.preventDefault();
    const form = event.currentTarget;
    try {
        const res = await postJson(API.fuelPrice, {
            regular_gtq_gal: Number(form.regular_gtq_gal.value),
            super_gtq_gal: Number(form.super_gtq_gal.value),
            diesel_gtq_gal: Number(form.diesel_gtq_gal.value),
            source: form.source.value || "Manual"
        });
        renderFuelPrice(res.fuel_price);
        form.style.display = "none";
        document.getElementById("btn-edit-fuel").style.display = "";
        showToast("Precio de combustible actualizado.");
    } catch (error) {
        showToast(error.message, true);
    }
}

function initDeptPresetSelect() {
    const sel = document.getElementById("dept-preset-select");
    GUATEMALA_DEPARTMENTS.forEach((d) => {
        const opt = document.createElement("option");
        opt.value = d.code;
        opt.textContent = `${d.name} (${d.code})`;
        sel.appendChild(opt);
    });
}

function onDeptPresetChange(event) {
    const code = event.target.value;
    if (!code) return;
    const preset = GUATEMALA_DEPARTMENTS.find((d) => d.code === code);
    if (!preset) return;
    const form = document.getElementById("department-form");
    form.code.value = preset.code;
    form.name.value = preset.name;
    form.latitude.value = preset.lat;
    form.longitude.value = preset.lng;
    event.target.value = "";
}

function bindFilters() {
    document.getElementById("dash-filter-btn").addEventListener("click", reloadDashboard);
    document.getElementById("dash-clear-btn").addEventListener("click", () => {
        document.getElementById("dash-date-from").value = "";
        document.getElementById("dash-date-to").value = "";
        reloadDashboard();
    });
    ["order-filter-status", "order-filter-origin", "order-filter-dest"].forEach((id) => {
        document.getElementById(id).addEventListener("change", renderOrdersFiltered);
    });
    ["trip-filter-status", "trip-filter-vehicle", "trip-filter-from", "trip-filter-to"].forEach((id) => {
        document.getElementById(id).addEventListener("change", renderTripsFiltered);
    });
}

async function reloadAll() {
    try {
        const [meRes, deptRes, connRes, storeRes, productRes, driverRes, vehicleRes, orderRes, tripRes, paymentRes, balanceRes, reportRes] = await Promise.all([
            getJson(API.me),
            getJson(API.departments),
            getJson(API.connections),
            getJson(API.stores),
            getJson(API.products),
            getJson(API.drivers),
            getJson(API.vehicles),
            getJson(API.orders),
            getJson(API.trips),
            getJson(API.payments),
            getJson(API.balances),
            getJson(API.reports)
        ]);
        state.currentUser = meRes.user;
        state.departments = deptRes.departments;
        state.connections = connRes.connections;
        state.stores = storeRes.stores;
        state.products = productRes.products;
        state.drivers = driverRes.drivers;
        state.vehicles = vehicleRes.vehicles;
        state.orders = orderRes.orders;
        state.trips = tripRes.trips;
        state.payments = paymentRes.payments;
        state.balances = balanceRes.balances;
        state.report = reportRes.report;

        await Promise.all([reloadDashboard(), reloadFuelPrice()]);

        if (state.currentUser && state.currentUser.role === "admin") {
            try {
                const usersRes = await getJson(API.users);
                state.users = usersRes.users;
            } catch (_) {}
        }

        renderAll();
        await refreshOfflineSummary();
    } catch (error) {
        showToast(error.message, true);
    }
}

async function reloadDashboard() {
    try {
        const from = document.getElementById("dash-date-from").value;
        const to = document.getElementById("dash-date-to").value;
        let url = API.dashboard;
        const params = [];
        if (from) params.push(`date_from=${from}`);
        if (to) params.push(`date_to=${to}`);
        if (params.length) url += "?" + params.join("&");
        const res = await getJson(url);
        state.dashboard = res.dashboard;
        renderDashboard();
    } catch (error) {
        showToast(error.message, true);
    }
}

function renderAll() {
    renderUserInfo();
    renderDashboard();
    renderDepartmentsInSelects();
    renderDepartments();
    renderStores();
    renderStoreSelects();
    renderProducts();
    renderProductSelects();
    updateOrderEstimate();
    renderDriverSelects();
    renderVehicles();
    renderDrivers();
    renderOrdersFiltered();
    renderPaymentStoreSelect();
    renderPaymentOrderSelect();
    renderPaymentTripSelect();
    renderPayments();
    renderBalances();
    renderReport();
    renderPlannerInputs();
    renderTripsFiltered();
    renderEventTripSelect();
    renderDeliveryTripSelect();
    renderTripFilterVehicles();
    if (window.google?.maps) renderMap();
    renderUsers();
    renderPendingUsers();
    renderBusinessDetails();
}

function renderUserInfo() {
    const user = state.currentUser;
    if (!user) return;
    document.getElementById("user-name").textContent = user.full_name || user.username;
    const badge = document.getElementById("user-badge");
    const roleLabels = { admin: "Admin", supervisor: "Supervisor", seller: "Vendedor/cobrador", driver: "Repartidor" };
    badge.textContent = roleLabels[user.role] || user.role;
    badge.className = `role-badge role-${user.role}`;

    const isAdmin = user.role === "admin";
    const isSupervisor = user.role === "supervisor" || isAdmin;
    const isSeller = user.role === "seller";
    const isDriver = user.role === "driver";

    const allowedTabs = {
        admin: ["dashboard", "planner", "trips", "map", "orders", "payments", "stores", "products", "vehicles", "drivers", "reports", "departments", "users"],
        supervisor: ["dashboard", "planner", "trips", "map", "orders", "payments", "stores", "products", "vehicles", "drivers", "reports", "departments"],
        seller: ["dashboard", "orders", "payments", "stores"],
        driver: ["dashboard", "trips", "map", "payments"],
    }[user.role] || ["dashboard"];
    document.querySelectorAll(".tab[data-tab]").forEach(button => {
        button.style.display = allowedTabs.includes(button.dataset.tab) ? "" : "none";
    });
    const active = document.querySelector(".tab.is-active");
    if (active && !allowedTabs.includes(active.dataset.tab)) document.querySelector('.tab[data-tab="dashboard"]')?.click();

    document.getElementById("vehicle-form-card").style.display = isSupervisor ? "" : "none";
    document.getElementById("store-form-card").style.display = (isSupervisor || isSeller) ? "" : "none";
    document.getElementById("product-form-card").style.display = isSupervisor ? "" : "none";
    document.getElementById("driver-form-card").style.display = isSupervisor ? "" : "none";
    document.getElementById("order-form-card").style.display = (isSupervisor || isSeller) ? "" : "none";
    document.getElementById("department-form-card").style.display = isSupervisor ? "" : "none";
    document.getElementById("btn-navigate-next").style.display = isDriver ? "" : "none";
    document.getElementById("btn-start-gps").style.display = isSupervisor ? "" : "none";
    document.getElementById("btn-sim-delivery").style.display = isSupervisor ? "" : "none";
}

function renderDashboard() {
    const dashboard = state.dashboard;
    if (!dashboard) return;

    const summary = dashboard.summary;
    setText("metric-total-trips", summary.total_trips);
    setText("metric-active-trips", summary.active_trips);
    setText("metric-pending-orders", summary.pending_orders);
    setText("metric-delivered-orders", summary.delivered_orders);
    setText("metric-total-cost", summary.total_cost.toFixed(2));
    setText("metric-total-distance", summary.total_distance_km.toFixed(2));

    const statusLabels = dashboard.status_distribution.map((item) => item.status);
    const statusValues = dashboard.status_distribution.map((item) => item.total);
    drawBarChart("status-chart", statusLabels, statusValues, "#f97316");

    const timelineLabels = dashboard.timeline.map((item) => item.date.slice(5));
    const timelineValues = dashboard.timeline.map((item) => item.trips);
    drawBarChart("timeline-chart", timelineLabels, timelineValues, "#0ea5a4");

    const body = document.getElementById("vehicle-activity-body");
    body.innerHTML = "";
    if (!dashboard.vehicle_activity.length) {
        body.innerHTML = `<tr><td colspan="2">No hay actividad registrada.</td></tr>`;
        return;
    }
    dashboard.vehicle_activity.forEach((item) => {
        body.insertAdjacentHTML(
            "beforeend",
            `<tr><td>${escapeHtml(item.plate)}</td><td>${item.total_trips}</td></tr>`
        );
    });
}

function renderDepartmentsInSelects() {
    const departmentOptions = [
        `<option value="">Seleccione...</option>`,
        ...state.departments.map(
            (d) => `<option value="${d.id}">${escapeHtml(d.name)} (${escapeHtml(d.code)})</option>`
        )
    ].join("");

    ["vehicle-current-department", "store-department", "order-origin", "order-destination"].forEach((id) => {
        const select = document.getElementById(id);
        if (!select) return;
        if (select.dataset.loaded === "1") {
            const previous = select.value;
            select.innerHTML = departmentOptions;
            if (previous) select.value = previous;
        } else {
            select.innerHTML = departmentOptions;
            select.dataset.loaded = "1";
        }
    });

    const filterOpts = [
        `<option value="">Todos</option>`,
        ...state.departments.map((d) => `<option value="${d.id}">${escapeHtml(d.name)}</option>`)
    ].join("");
    document.getElementById("order-filter-origin").innerHTML = filterOpts;
    document.getElementById("order-filter-dest").innerHTML = filterOpts;
}

function renderStoreSelects() {
    const activeStores = state.stores.filter((store) => store.is_active);
    const options = [
        `<option value="">Seleccione cliente...</option>`,
        ...activeStores.map((store) => {
            const place = [store.municipality, store.neighborhood].filter(Boolean).join(" / ");
            const label = `${store.name} - ${place || store.department_name}`;
            return `<option value="${store.id}">${escapeHtml(label)}</option>`;
        })
    ].join("");
    const select = document.getElementById("order-store");
    if (select) select.innerHTML = options;
}

function renderStores() {
    const body = document.getElementById("stores-body");
    if (!body) return;
    body.innerHTML = "";
    if (!state.stores.length) {
        body.innerHTML = `<tr><td colspan="11">No hay tiendas registradas.</td></tr>`;
        return;
    }
    state.stores.forEach((store) => {
        body.insertAdjacentHTML(
            "beforeend",
            `<tr>
                <td><strong>${escapeHtml(store.name)}</strong><br><small>${escapeHtml(store.address || store.reference || "-")}</small></td>
                <td>${escapeHtml(store.department_name)}</td>
                <td>${productTypeLabel(store.product_type)}</td>
                <td>${visitFrequencyLabel(store.visit_frequency)}</td>
                <td>${escapeHtml(store.phone || "-")}</td>
                <td>${escapeHtml(store.municipality || "-")}</td>
                <td>${escapeHtml(store.neighborhood || "-")}</td>
                <td>${Number(store.latitude).toFixed(5)}, ${Number(store.longitude).toFixed(5)}</td>
                <td>${statusChip(store.is_active ? "active" : "inactive")}</td>
                <td><button type="button" class="btn-inline" data-focus-store="${store.id}">Ver</button></td>
                <td>${(["admin", "supervisor", "seller"].includes(state.currentUser?.role) ? `<button type="button" class="btn-inline" data-edit-store="${store.id}">Editar</button>` : "") + deleteButton("stores", store.id, store.name) || "-"}</td>
            </tr>`
        );
    });
}

function renderProducts() {
    const body = document.getElementById("products-body");
    if (!body) return;
    body.innerHTML = "";
    if (!state.products.length) {
        body.innerHTML = `<tr><td colspan="7">No hay productos registrados.</td></tr>`;
        return;
    }
    state.products.forEach((product) => {
        body.insertAdjacentHTML(
            "beforeend",
            `<tr>
                <td>${escapeHtml(product.name)}</td>
                <td>${productTypeLabel(product.product_type)}</td>
                <td>${escapeHtml(product.presentation || "-")}</td>
                <td>Q ${Number(product.unit_price).toFixed(2)}</td>
                <td>${Number(product.unit_weight_kg).toFixed(2)} kg</td>
                <td>${statusChip(product.is_active ? "active" : "inactive")}</td>
                <td>${deleteButton("products", product.id, product.name) || "-"}</td>
            </tr>`
        );
    });
}

function renderProductSelects() {
    const select = document.getElementById("order-product");
    if (!select) return;
    const activeProducts = state.products.filter((product) => product.is_active);
    select.innerHTML = [
        `<option value="">Seleccione producto...</option>`,
        ...activeProducts.map((product) => {
            const label = `${product.name} ${product.presentation || ""} - Q ${Number(product.unit_price).toFixed(2)}`;
            return `<option value="${product.id}">${escapeHtml(label)}</option>`;
        })
    ].join("");
}

function updateOrderEstimate() {
    const form = document.getElementById("order-form");
    if (!form) return;
    const product = state.products.find((item) => String(item.id) === form.product_id.value);
    const quantity = Number(form.quantity.value || 0);
    if (!product || !quantity) {
        form.weight_kg.value = "";
        form.total_amount.value = "";
        return;
    }
    form.weight_kg.value = (Number(product.unit_weight_kg) * quantity).toFixed(2);
    form.total_amount.value = `Q ${(Number(product.unit_price) * quantity).toFixed(2)}`;
}

function renderDepartments() {
    const body = document.getElementById("departments-body");
    if (!body) return;
    body.innerHTML = "";
    if (!state.departments.length) {
        body.innerHTML = `<tr><td colspan="5">No hay zonas registradas.</td></tr>`;
        return;
    }
    state.departments.forEach((d) => {
        body.insertAdjacentHTML(
            "beforeend",
            `<tr>
                <td>${escapeHtml(d.code)}</td>
                <td>${escapeHtml(d.name)}</td>
                <td>${d.latitude !== null && d.latitude !== undefined ? d.latitude : "-"}</td>
                <td>${d.longitude !== null && d.longitude !== undefined ? d.longitude : "-"}</td>
                <td>${deleteButton("departments", d.id, d.name) || "-"}</td>
            </tr>`
        );
    });
}

function renderDriverSelects() {
    const activeDrivers = state.drivers.filter((d) => d.is_active);
    const opts = [
        `<option value="">Sin repartidor</option>`,
        ...activeDrivers.map((d) => `<option value="${d.id}">${escapeHtml(d.name)} (${escapeHtml(d.license_number)})</option>`)
    ].join("");
    document.getElementById("vehicle-driver").innerHTML = opts;
    document.getElementById("planner-driver").innerHTML = [
        `<option value="">Sin repartidor asignado</option>`,
        ...activeDrivers.map((d) => `<option value="${d.id}">${escapeHtml(d.name)}</option>`)
    ].join("");
}

function renderVehicles() {
    const body = document.getElementById("vehicles-body");
    body.innerHTML = "";
    if (!state.vehicles.length) {
        body.innerHTML = `<tr><td colspan="9">No hay vehiculos registrados.</td></tr>`;
        return;
    }
    state.vehicles.forEach((v) => {
        body.insertAdjacentHTML(
            "beforeend",
            `<tr>
                <td>${escapeHtml(v.plate)}</td>
                <td>${escapeHtml(v.model)}</td>
                <td>${v.capacity_kg.toFixed(2)} kg</td>
                <td>${v.fuel_efficiency_km_l.toFixed(2)} km/l</td>
                <td>Q ${v.cost_per_km.toFixed(2)}</td>
                <td>${escapeHtml(v.driver_name || "-")}</td>
                <td>${escapeHtml(v.current_department_name || "-")}</td>
                <td>${statusChip(v.is_active ? "active" : "inactive")}</td>
                <td>${deleteButton("vehicles", v.id, v.plate) || "-"}</td>
            </tr>`
        );
    });
}

function renderDrivers() {
    const body = document.getElementById("drivers-body");
    body.innerHTML = "";
    if (!state.drivers.length) {
        body.innerHTML = `<tr><td colspan="5">No hay repartidores registrados.</td></tr>`;
        return;
    }
    state.drivers.forEach((d) => {
        body.insertAdjacentHTML(
            "beforeend",
            `<tr>
                <td>${escapeHtml(d.name)}</td>
                <td>${escapeHtml(d.phone || "-")}</td>
                <td>${escapeHtml(d.license_number)}</td>
                <td>${statusChip(d.is_active ? "active" : "inactive")}</td>
                <td>${deleteButton("drivers", d.id, d.name) || "-"}</td>
            </tr>`
        );
    });
}

function renderOrdersFiltered() {
    const statusVal = document.getElementById("order-filter-status").value;
    const originVal = document.getElementById("order-filter-origin").value;
    const destVal = document.getElementById("order-filter-dest").value;

    const filtered = state.orders.filter((o) => {
        if (statusVal && o.status !== statusVal) return false;
        if (originVal && String(o.origin_id) !== originVal) return false;
        if (destVal && String(o.destination_id) !== destVal) return false;
        return true;
    });

    const body = document.getElementById("orders-body");
    body.innerHTML = "";
    if (!filtered.length) {
        body.innerHTML = `<tr><td colspan="9">No hay entregas con estos filtros.</td></tr>`;
        return;
    }
    filtered.forEach((o) => {
        const products = (o.items || []).map((item) => `${item.quantity} x ${item.product_name}`).join(", ") || `${o.package_count} unidades`;
        body.insertAdjacentHTML(
            "beforeend",
            `<tr>
                <td>${escapeHtml(o.code)}</td>
                <td>${escapeHtml(o.origin_name)}${o.departure_latitude != null
                    ? `<br><small>Salida: ${Number(o.departure_latitude).toFixed(5)}, ${Number(o.departure_longitude).toFixed(5)}${o.departure_accuracy_m != null ? ` · GPS ±${Math.ceil(o.departure_accuracy_m)} m` : " · manual"}</small>`
                    : ""}</td>
                <td>${escapeHtml(o.store_name || o.destination_name)}</td>
                <td>${o.weight_kg.toFixed(2)} kg</td>
                <td>${escapeHtml(products)}</td>
                <td>Q ${Number(o.balance_due || 0).toFixed(2)}<br><small>${paymentStatusLabel(o)}</small></td>
                <td>${priorityLabel(o.priority)}</td>
                <td>${statusChip(o.status)}</td>
                <td>${(["admin", "supervisor"].includes(state.currentUser?.role) && ["pending", "assigned"].includes(o.status) && !o.paid_amount ? `<button type="button" data-cancel-order="${o.id}">Cancelar pedido</button>` : "") + (["pending", "canceled"].includes(o.status) && !o.paid_amount ? deleteButton("orders", o.id, o.code) : "") || "-"}</td>
            </tr>`
        );
    });
}

function renderPaymentStoreSelect() {
    const select = document.getElementById("payment-store");
    if (!select) return;
    const previous = select.value;
    const options = [
        `<option value="">Seleccione tienda...</option>`,
        ...state.stores.filter((store) => store.is_active).map((store) => `<option value="${store.id}">${escapeHtml(store.name)}</option>`)
    ].join("");
    select.innerHTML = options;
    if (previous) select.value = previous;
}

function renderPaymentOrderSelect() {
    const select = document.getElementById("payment-order");
    const storeSelect = document.getElementById("payment-store");
    if (!select || !storeSelect) return;
    const storeId = storeSelect.value;
    const storeOrders = state.orders.filter((order) => String(order.store_id || "") === storeId && Number(order.balance_due || 0) > 0);
    select.innerHTML = [
        `<option value="">Sin pedido especifico</option>`,
        ...storeOrders.map((order) => `<option value="${order.id}">${escapeHtml(order.code)} - saldo Q ${Number(order.balance_due || 0).toFixed(2)}</option>`)
    ].join("");
}

function renderPayments() {
    const body = document.getElementById("payments-body");
    if (!body) return;
    body.innerHTML = "";
    if (!state.payments.length) {
        body.innerHTML = `<tr><td colspan="6">No hay cobros registrados.</td></tr>`;
        return;
    }
    state.payments.forEach((payment) => {
        body.insertAdjacentHTML(
            "beforeend",
            `<tr>
                <td>${escapeHtml(payment.store_name)}</td>
                <td>${escapeHtml(payment.order_code || "-")}</td>
                <td>Q ${Number(payment.amount).toFixed(2)}</td>
                <td>${paymentTypeLabel(payment.payment_type)}</td>
                <td>${paymentMethodLabel(payment.method)}</td>
                <td>${escapeHtml(payment.sync_status)}</td>
            </tr>`
        );
    });
}

function renderBalances() {
    const body = document.getElementById("balances-body");
    if (!body) return;
    body.innerHTML = "";
    if (!state.balances.length) {
        body.innerHTML = `<tr><td colspan="6">No hay saldos pendientes.</td></tr>`;
        return;
    }
    state.balances.forEach((row) => {
        body.insertAdjacentHTML(
            "beforeend",
            `<tr>
                <td>${escapeHtml(row.store_name)}</td>
                <td>${escapeHtml(row.municipality || "-")}</td>
                <td>${escapeHtml(row.neighborhood || "-")}</td>
                <td>Q ${Number(row.sales_total).toFixed(2)}</td>
                <td>Q ${Number(row.paid_total).toFixed(2)}</td>
                <td><strong>Q ${Number(row.balance_due).toFixed(2)}</strong></td>
            </tr>`
        );
    });
}

function renderReport() {
    const report = state.report;
    if (!report) return;
    setText("report-sales", Number(report.sales_total).toFixed(2));
    setText("report-paid", Number(report.paid_total).toFixed(2));
    setText("report-balance", Number(report.balance_due).toFixed(2));
    setText("report-orders", report.orders);
    setText("report-trips", report.trips);
    setText("report-fuel", Number(report.fuel_cost_gtq).toFixed(2));
}

function renderPlannerInputs() {
    const vehicleSelect = document.getElementById("planner-vehicle");
    const activeVehicles = state.vehicles.filter((v) => v.is_active);
    vehicleSelect.innerHTML = [
        `<option value="">Seleccione un vehiculo...</option>`,
        ...activeVehicles.map((v) => `<option value="${v.id}">${escapeHtml(v.plate)} - ${escapeHtml(v.model)}</option>`)
    ].join("");

    const pendingOrders = state.orders.filter((o) => o.status === "pending");
    const checklist = document.getElementById("planner-orders-list");
    checklist.innerHTML = "";
    if (!pendingOrders.length) {
        checklist.innerHTML = `<p>No hay entregas pendientes.</p>`;
        return;
    }
    pendingOrders.forEach((order) => {
        checklist.insertAdjacentHTML(
            "beforeend",
            `<label class="check-item">
                <input type="checkbox" value="${order.id}" name="order_ids">
                <span>
                    <strong>${escapeHtml(order.code)}</strong> ${escapeHtml(order.origin_name)} -> ${escapeHtml(order.store_name || order.destination_name)}
                    <br>
                    <small>${order.weight_kg.toFixed(2)} kg | ${order.package_count} productos | prioridad ${priorityLabel(order.priority)}</small>
                </span>
            </label>`
        );
    });
}

function renderTripFilterVehicles() {
    const sel = document.getElementById("trip-filter-vehicle");
    sel.innerHTML = [
        `<option value="">Todos</option>`,
        ...state.vehicles.map((v) => `<option value="${v.id}">${escapeHtml(v.plate)}</option>`)
    ].join("");
}

function renderTripsFiltered() {
    const statusVal = document.getElementById("trip-filter-status").value;
    const vehicleVal = document.getElementById("trip-filter-vehicle").value;
    const fromVal = document.getElementById("trip-filter-from").value;
    const toVal = document.getElementById("trip-filter-to").value;

    const filtered = state.trips.filter((t) => {
        if (statusVal && t.status !== statusVal) return false;
        if (vehicleVal && String(t.vehicle_id) !== vehicleVal) return false;
        if (fromVal && t.started_at && t.started_at.slice(0, 10) < fromVal) return false;
        if (toVal && t.started_at && t.started_at.slice(0, 10) > toVal) return false;
        return true;
    });

    const body = document.getElementById("trips-body");
    body.innerHTML = "";
    if (!filtered.length) {
        body.innerHTML = `<tr><td colspan="9">No hay rutas con estos filtros.</td></tr>`;
        return;
    }
    filtered.forEach((trip) => {
        body.insertAdjacentHTML(
            "beforeend",
            `<tr>
                <td>${escapeHtml(trip.code)}</td>
                <td>${escapeHtml(trip.vehicle_plate)}</td>
                <td>${escapeHtml(trip.driver_name || "-")}</td>
                <td>${escapeHtml(trip.route_nodes.join(" → "))}</td>
                <td>${trip.total_distance_km.toFixed(2)} km</td>
                <td>${trip.estimated_fuel_gallons.toFixed(2)} gal</td>
                <td>Q ${trip.estimated_cost.toFixed(2)}</td>
                <td>${statusChip(trip.status)}</td>
                <td>${buildTripActions(trip)}</td>
            </tr>`
        );
    });
}

function renderEventTripSelect() {
    const select = document.getElementById("event-trip-id");
    select.innerHTML = [
        `<option value="">Seleccione...</option>`,
        ...state.trips.map((trip) => `<option value="${trip.id}">${escapeHtml(trip.code)} (${statusLabel(trip.status)})</option>`)
    ].join("");
}

function renderMapTripSelect() {
    const sel = document.getElementById("map-trip-select");
    const previousSelection = selectedMapTripId || Number(sel.value || 0);
    sel.innerHTML = [
        `<option value="">Ninguno</option>`,
        ...state.trips.map((trip) => `<option value="${trip.id}">${escapeHtml(trip.code)} - ${escapeHtml(trip.route_nodes.join(" -> "))}</option>`)
    ].join("");

    if (previousSelection && state.trips.some((trip) => trip.id === previousSelection)) {
        sel.value = String(previousSelection);
        selectedMapTripId = previousSelection;
    } else {
        sel.value = "";
        selectedMapTripId = null;
    }
}

function renderUsers() {
    const body = document.getElementById("users-body");
    if (!body) return;
    body.innerHTML = "";
    if (!state.users.length) {
        body.innerHTML = `<tr><td colspan="6">No hay usuarios registrados.</td></tr>`;
        return;
    }
    const roleLabels = { admin: "Administrador", supervisor: "Supervisor", seller: "Vendedor/cobrador", driver: "Repartidor" };
    state.users.forEach((u) => {
        body.insertAdjacentHTML(
            "beforeend",
            `<tr>
                <td>${escapeHtml(u.username)}</td>
                <td>${escapeHtml(u.full_name || "-")}</td>
                <td>${escapeHtml(u.email || "-")}</td>
                <td><span class="role-badge role-${u.role}">${roleLabels[u.role] || u.role}</span></td>
                <td>${statusChip(u.is_active ? "active" : "inactive")}</td>
                <td>${u.is_active ? "—" : `<button type="button" class="btn-inline" data-approve-user="${u.id}" data-user-role="${u.role}">Aprobar cuenta</button>`}</td>
            </tr>`
        );
    });
}

function renderPendingUsers() {
    const card = document.getElementById("pending-accounts-card");
    const body = document.getElementById("pending-users-body");
    if (!card || !body) return;
    const pending = state.currentUser?.role === "admin" ? state.users.filter(user => !user.is_active) : [];
    card.style.display = pending.length ? "" : "none";
    document.getElementById("pending-users-count").textContent = String(pending.length);
    const roleLabels = { admin: "Administrador", supervisor: "Supervisor", seller: "Vendedor/cobrador", driver: "Repartidor" };
    body.innerHTML = pending.map(user => `<tr>
        <td>${escapeHtml(user.username)}</td>
        <td>${escapeHtml(user.full_name || "-")}</td>
        <td><span class="role-badge role-${user.role}">${roleLabels[user.role] || escapeHtml(user.role)}</span></td>
        <td><button type="button" class="btn-inline" data-approve-user="${user.id}" data-user-role="${user.role}">Aprobar cuenta</button></td>
    </tr>`).join("");
}

async function onUserApprovalClick(event) {
    const button = event.target.closest("[data-approve-user]");
    if (!button) return;
    button.disabled = true;
    try {
        await postJson(`/api/users/${button.dataset.approveUser}/`, {
            role: button.dataset.userRole,
            is_active: true
        }, makeLocalId());
        state.users = (await getJson(API.users)).users;
        renderUsers();
        renderPendingUsers();
        renderBusinessDetails();
        showToast("Cuenta aprobada. El empleado ya puede iniciar sesión.");
    } catch (error) {
        showToast(error.message, true);
        button.disabled = false;
    }
}

// â”€â”€ MAP â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

function renderMap() {
    const depts = state.departments.filter((d) => d.latitude && d.longitude);
    if (!depts.length) return;

    if (!map) {
        map = new google.maps.Map(document.getElementById("route-map"), {
            center: { lat: 15.45, lng: -90.3 },
            zoom: 7,
            mapTypeId: "roadmap",
            streetViewControl: false,
            rotateControl: false
        });
        new google.maps.TrafficLayer().setMap(map);
        directionsRenderer = new google.maps.DirectionsRenderer({
            suppressMarkers: true,
            polylineOptions: {
                strokeColor: "#1a73e8",
                strokeOpacity: 0.9,
                strokeWeight: 5
            }
        });
        directionsRenderer.setMap(map);
    }

    renderMapTripSelect();
    updateMapData();
}

function onMapTripSelect(event) {
    const tripId = Number(event.target.value || 0);
    focusMapTripById(tripId, { shouldFit: true });
}

function fetchRoadGeometryGoogleMaps(waypointCoords) {
    return new Promise((resolve, reject) => {
        const svc = new google.maps.DirectionsService();
        const origin = { lat: waypointCoords[0][1], lng: waypointCoords[0][0] };
        const destination = {
            lat: waypointCoords[waypointCoords.length - 1][1],
            lng: waypointCoords[waypointCoords.length - 1][0]
        };
        const waypoints = waypointCoords.slice(1, -1).map(([lng, lat]) => ({
            location: { lat, lng },
            stopover: true
        }));
        svc.route({
            origin,
            destination,
            waypoints,
            travelMode: google.maps.TravelMode.DRIVING
        }, (result, status) => {
            if (status !== "OK") {
                reject(new Error(`Directions API: ${status}`));
                return;
            }
            resolve(result);
        });
    });
}

async function focusMapTripById(tripId, options = {}) {
    const { shouldFit = true } = options;

    if (!tripId) {
        selectedMapTripId = null;
        clearHighlightedRoute();
        updateMapRouteSummary(null);
        return;
    }

    const trip = state.trips.find((t) => t.id === tripId);
    if (!trip) {
        selectedMapTripId = null;
        clearHighlightedRoute();
        updateMapRouteSummary(null);
        return;
    }

    const waypointCoords = [];
    const routeLabels = [];
    const origin = state.departments.find((department) => department.name === trip.origin_name);
    if (origin?.latitude && origin?.longitude) {
        waypointCoords.push([Number(origin.longitude), Number(origin.latitude)]);
        routeLabels.push(`Base: ${origin.name}`);
    }
    [...(trip.stops || [])].sort((a, b) => a.sequence - b.sequence).forEach((stop) => {
        if (stop.latitude == null || stop.longitude == null) return;
        waypointCoords.push([Number(stop.longitude), Number(stop.latitude)]);
        routeLabels.push(stop.store_name || stop.order_code || `Parada ${stop.sequence}`);
    });

    if (waypointCoords.length < 2) {
        selectedMapTripId = null;
        clearHighlightedRoute();
        updateMapRouteSummary(null);
        return;
    }

    selectedMapTripId = tripId;
    updateMapRouteSummary(trip);
    clearHighlightedRoute();

    const addWaypointMarkers = () => {
        waypointCoords.forEach(([lng, lat], index) => {
            const isFirst = index === 0;
            const isLast = index === waypointCoords.length - 1;
            const color = isFirst ? "#22c55e" : isLast ? "#ef4444" : "#f59e0b";
            const marker = new google.maps.Marker({
                position: { lat, lng },
                map,
                title: routeLabels[index] || "",
                icon: {
                    path: google.maps.SymbolPath.CIRCLE,
                    scale: isFirst || isLast ? 10 : 7,
                    fillColor: color,
                    fillOpacity: 1,
                    strokeColor: "#ffffff",
                    strokeWeight: 2.5
                },
                zIndex: 20
            });
            gmapRouteMarkers.push(marker);
        });
    };

    try {
        const result = await fetchRoadGeometryGoogleMaps(waypointCoords);
        if (selectedMapTripId !== tripId) return;
        lastDirectionsResult = result;
        if (typeof saveOfflineRoute === "function") saveOfflineRoute(tripId, result.routes[0].overview_path);
        directionsRenderer.setDirections(result);
        addWaypointMarkers();
        if (shouldFit && result.routes[0]?.bounds) {
            map.fitBounds(result.routes[0].bounds, 48);
        }
    } catch (err) {
        console.warn("No se pudo calcular el recorrido por carretera:", err.message);
        addWaypointMarkers();
        showToast("No se pudo calcular la carretera. Revisa la conexión y la configuración de Google Routes.", true);
        if (shouldFit) {
            const bounds = new google.maps.LatLngBounds();
            waypointCoords.forEach(([lng, lat]) => bounds.extend({ lat, lng }));
            map.fitBounds(bounds, 48);
        }
    }
}

function updateMapData() {
    gmapMarkers.forEach((m) => m.setMap(null));
    gmapMarkers = [];
    gmapStoreMarkers.forEach((m) => m.setMap(null));
    gmapStoreMarkers = [];
    gmapConnections.forEach((p) => p.setMap(null));
    gmapConnections = [];

    state.departments.filter((d) => d.latitude && d.longitude).forEach((dept) => {
        const marker = new google.maps.Marker({
            position: { lat: Number(dept.latitude), lng: Number(dept.longitude) },
            map,
            title: dept.name,
            icon: {
                path: google.maps.SymbolPath.CIRCLE,
                scale: 8,
                fillColor: "#fb923c",
                fillOpacity: 1,
                strokeColor: "#ffffff",
                strokeWeight: 2.2
            },
            label: {
                text: dept.code,
                color: "#ffffff",
                fontSize: "10px",
                fontWeight: "bold"
            }
        });
        marker.addListener("click", () => {
            if (activeInfoWindow) activeInfoWindow.close();
            activeInfoWindow = new google.maps.InfoWindow({
                content: `<div style="font-family:sans-serif;padding:2px"><strong>${escapeHtml(dept.name)}</strong><br><small>${escapeHtml(dept.code)}</small></div>`
            });
            activeInfoWindow.open(map, marker);
        });
        gmapMarkers.push(marker);
    });

    state.stores.filter((store) => store.is_active && store.latitude && store.longitude).forEach((store) => {
        const marker = new google.maps.Marker({
            position: { lat: Number(store.latitude), lng: Number(store.longitude) },
            map,
            title: store.name,
            icon: {
                path: google.maps.SymbolPath.CIRCLE,
                scale: 13,
                fillColor: store.product_type === "gas" ? "#ef4444" : "#0ea5a4",
                fillOpacity: 1,
                strokeColor: "#0f172a",
                strokeWeight: 2.5
            },
            label: {
                text: "T",
                color: "#ffffff",
                fontSize: "12px",
                fontWeight: "bold"
            },
            zIndex: 24
        });
        marker.storeId = store.id;
        marker.addListener("click", () => {
            if (activeInfoWindow) activeInfoWindow.close();
            activeInfoWindow = new google.maps.InfoWindow({
                content: `
                    <div style="font-family:sans-serif;max-width:240px;padding:2px">
                        <strong>${escapeHtml(store.name)}</strong><br>
                        <small>${escapeHtml(productTypeLabel(store.product_type))} | ${escapeHtml(store.department_name)}</small><br>
                        <small>${escapeHtml(store.municipality || "Sin municipio")} / ${escapeHtml(store.neighborhood || "Sin colonia")}</small><br>
                        <small>${escapeHtml(store.phone || "Sin telefono")}</small><br>
                        <small><strong>Direccion:</strong> ${escapeHtml(store.address || "Sin direccion")}</small><br>
                        <small><strong>Referencia:</strong> ${escapeHtml(store.reference || "-")}</small><br>
                        <small>GPS: ${Number(store.latitude).toFixed(6)}, ${Number(store.longitude).toFixed(6)}</small>
                    </div>`
            });
            activeInfoWindow.open(map, marker);
        });
        gmapStoreMarkers.push(marker);
    });

    if (selectedMapTripId && state.trips.some((t) => t.id === selectedMapTripId)) {
        focusMapTripById(selectedMapTripId, { shouldFit: false });
        return;
    }

    selectedMapTripId = null;
    const selector = document.getElementById("map-trip-select");
    if (selector) selector.value = "";
    clearHighlightedRoute();
    updateMapRouteSummary(null);
    fitMapToDepartments();
}

function clearHighlightedRoute() {
    lastDirectionsResult = null;
    stopGpsSimulation();
    if (directionsRenderer) directionsRenderer.setDirections({ routes: [] });
    gmapRouteMarkers.forEach((m) => m.setMap(null));
    gmapRouteMarkers = [];
}

function fitMapToDepartments() {
    if (mapHasAutoFit) return;
    const depts = state.departments.filter((d) => d.latitude && d.longitude);
    const stores = state.stores.filter((store) => store.is_active && store.latitude && store.longitude);
    if (depts.length + stores.length < 2) return;
    const bounds = new google.maps.LatLngBounds();
    depts.forEach((d) => bounds.extend({ lat: Number(d.latitude), lng: Number(d.longitude) }));
    stores.forEach((store) => bounds.extend({ lat: Number(store.latitude), lng: Number(store.longitude) }));
    map.fitBounds(bounds);
    mapHasAutoFit = true;
}

function updateMapRouteSummary(trip) {
    const summary = document.getElementById("map-route-summary");
    const hint = document.getElementById("map-summary-hint");
    const stopsBox = document.getElementById("map-route-stops");
    if (!summary || !hint) return;
    if (!trip) {
        summary.classList.add("is-empty");
        hint.textContent = "Selecciona una ruta para ver el recorrido destacado.";
        setSummaryField("map-summary-code", "-");
        setSummaryField("map-summary-origin", "-");
        setSummaryField("map-summary-destination", "-");
        setSummaryField("map-summary-distance", "-");
        setSummaryField("map-summary-cost", "-");
        setSummaryField("map-summary-fuel", "-");
        setSummaryField("map-summary-status", "-");
        if (stopsBox) stopsBox.innerHTML = "";
        return;
    }
    summary.classList.remove("is-empty");
    hint.textContent = "Recorrido de conducción calculado por carretera, con inicio, tiendas y destino.";
    const storeNames = trip.orders
        .map((order) => order.store_name)
        .filter(Boolean);
    setSummaryField("map-summary-code", escapeHtml(trip.code));
    setSummaryField("map-summary-origin", escapeHtml(trip.origin_name));
    setSummaryField("map-summary-destination", escapeHtml(storeNames.length ? storeNames.join(", ") : trip.destination_name));
    setSummaryField("map-summary-distance", `${trip.total_distance_km.toFixed(2)} km`);
    setSummaryField("map-summary-cost", `Q ${trip.estimated_cost.toFixed(2)}`);
    setSummaryField("map-summary-fuel", `${trip.estimated_fuel_gallons.toFixed(2)} gal`);
    setSummaryField("map-summary-status", statusChip(trip.status));
    renderMapStops(trip);
}

function renderMapStops(trip) {
    const stopsBox = document.getElementById("map-route-stops");
    if (!stopsBox) return;
    const stops = [...(trip.stops || [])].sort((a, b) => a.sequence - b.sequence);
    if (!stops.length) {
        stopsBox.innerHTML = "";
        return;
    }
    stopsBox.innerHTML = `
        <h5>Paradas del repartidor</h5>
        <div class="route-stop-list">
            ${stops.map((stop) => `
                <article class="route-stop-item">
                    <div>
                        <strong>${stop.sequence}. ${escapeHtml(stop.store_name || stop.order_code || "Parada")}</strong>
                        <span>${statusChip(stop.status)} ${stop.observation ? escapeHtml(stop.observation) : ""}</span>
                    </div>
                    <div class="route-stop-actions">
                        ${state.currentUser?.role === "driver" && stop.status === "pending"
                            ? `<button type="button" class="btn-inline" data-open-delivery-stop="${stop.id}">Verificar llegada con GPS</button>`
                            : ["admin", "supervisor"].includes(state.currentUser?.role) && stop.status === "pending"
                                ? `<span class="gps-sim-hint">La entrega requiere llegada GPS del repartidor.</span>`
                                : ""}
                    </div>
                </article>
            `).join("")}
        </div>
    `;
}

async function onRouteStopAction(event) {
    const openDelivery = event.target.closest("button[data-open-delivery-stop]");
    if (openDelivery && selectedMapTripId) {
        document.querySelector('[data-tab="trips"]')?.click();
        document.getElementById("delivery-trip").value = String(selectedMapTripId);
        renderDeliveryStops();
        document.getElementById("delivery-stop").value = openDelivery.dataset.openDeliveryStop;
        document.getElementById("delivery-location-form").scrollIntoView({ behavior: "smooth", block: "start" });
        return;
    }
    const button = event.target.closest("button[data-stop-id][data-stop-status]");
    if (!button || !selectedMapTripId) return;
    const stopId = Number(button.dataset.stopId);
    const status = button.dataset.stopStatus;
    const observation = status === "not_delivered" ? "Marcado desde app movil" : "";
    try {
        const response = await postJsonOrQueue(
            `/api/trips/${selectedMapTripId}/stops/${stopId}/`,
            { status, observation },
            status === "delivered" ? "Marcar parada entregada" : "Marcar parada no entregada"
        );
        showToast(response.queued ? "Parada guardada sin conexion." : "Parada actualizada.");
        if (response.queued) return;
        await reloadAll();
        focusMapTripById(selectedMapTripId, { shouldFit: false });
    } catch (error) {
        showToast(error.message, true);
    }
}

function calcBearing(p1, p2) {
    const lat1 = p1.lat() * Math.PI / 180;
    const lat2 = p2.lat() * Math.PI / 180;
    const dLng = (p2.lng() - p1.lng()) * Math.PI / 180;
    const y = Math.sin(dLng) * Math.cos(lat2);
    const x = Math.cos(lat1) * Math.sin(lat2) - Math.sin(lat1) * Math.cos(lat2) * Math.cos(dLng);
    return (Math.atan2(y, x) * 180 / Math.PI + 360) % 360;
}

function startGpsSimulation() {
    if (!selectedMapTripId) {
        showToast("Selecciona una ruta en el mapa primero.", true);
        return;
    }
    if (!lastDirectionsResult || !lastDirectionsResult.routes.length) {
        showToast("Espera que cargue la ruta vial o selecciona una ruta distinta.", true);
        return;
    }
    stopGpsSimulation();

    const path = lastDirectionsResult.routes[0].overview_path;
    if (path.length < 2) {
        showToast("La ruta no tiene suficientes puntos para simular.", true);
        return;
    }

    let step = 0;
    const carSvg = encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="36" height="36" viewBox="0 0 36 36"><text x="2" y="30" font-size="30">🚗</text></svg>');
    const carIcon = {
        url: `data:image/svg+xml;charset=UTF-8,${carSvg}`,
        scaledSize: new google.maps.Size(36, 36),
        anchor: new google.maps.Point(18, 18)
    };

    gpsSimMarker = new google.maps.Marker({
        position: path[0],
        map,
        title: "Vehiculo en ruta",
        icon: carIcon,
        zIndex: 30
    });

    document.getElementById("btn-start-gps").style.display = "none";
    document.getElementById("btn-stop-gps").style.display = "";
    const hint = document.getElementById("gps-sim-status");
    if (hint) hint.textContent = `Simulando ${path.length} puntos...`;

    gpsSimTimer = setInterval(() => {
        step++;
        if (step >= path.length) {
            clearInterval(gpsSimTimer);
            gpsSimTimer = null;
            gpsSimMarker.setPosition(path[path.length - 1]);
            if (hint) hint.textContent = "El vehículo llegó al destino siguiendo la carretera.";
            if (typeof showSimulatedArrivalDialog === "function") showSimulatedArrivalDialog();
            showToast("El vehículo llegó al destino por el recorrido vial.");
            return;
        }
        gpsSimMarker.setPosition(path[step]);
        map.panTo(path[step]);
    }, 150);
}

function stopGpsSimulation() {
    if (gpsSimTimer) {
        clearInterval(gpsSimTimer);
        gpsSimTimer = null;
    }
    if (gpsSimMarker) {
        gpsSimMarker.setMap(null);
        gpsSimMarker = null;
    }
    const startBtn = document.getElementById("btn-start-gps");
    const stopBtn = document.getElementById("btn-stop-gps");
    const hint = document.getElementById("gps-sim-status");
    if (startBtn) startBtn.style.display = "";
    if (stopBtn) stopBtn.style.display = "none";
    if (hint) hint.textContent = "";
}

function sleep(ms) {
    return new Promise((resolve) => window.setTimeout(resolve, ms));
}

async function simulateDelivery(tripId) {
    if (deliverySimTimer) {
        showToast("Ya hay una simulacion de entrega en curso.", true);
        return;
    }
    if (!tripId) {
        showToast("Selecciona una ruta para simular la entrega.", true);
        return;
    }

    let trip = state.trips.find((item) => item.id === tripId);
    if (!trip) {
        showToast("No se encontro la ruta seleccionada.", true);
        return;
    }
    if (trip.status === "completed" || trip.status === "canceled") {
        showToast("Esta ruta ya no se puede simular porque esta cerrada.", true);
        return;
    }

    deliverySimTimer = window.setTimeout(() => { deliverySimTimer = null; }, 1000);
    document.querySelector('[data-tab="map"]')?.click();
    await focusMapTripById(tripId, { shouldFit: true });
    startGpsSimulation();
    showToast("Demostración iniciada. No modificará entregas reales.");
}

function setSummaryField(id, value) {
    const node = document.getElementById(id);
    if (!node) return;
    if (typeof value === "string" && value.includes("<")) {
        node.innerHTML = value;
        return;
    }
    node.textContent = value;
}

// â”€â”€ FORM HANDLERS â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

async function onVehicleSubmit(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const payload = {
        plate: form.plate.value.trim(),
        model: form.model.value.trim(),
        capacity_kg: Number(form.capacity_kg.value),
        fuel_efficiency_km_l: Number(form.fuel_efficiency_km_l.value),
        cost_per_km: Number(form.cost_per_km.value),
        current_department_id: form.current_department_id.value ? Number(form.current_department_id.value) : null,
        driver_id: form.driver_id.value ? Number(form.driver_id.value) : null,
        is_active: form.is_active.checked
    };
    try {
        await postJson(API.vehicles, payload);
        form.reset();
        showToast("Vehiculo registrado.");
        await reloadAll();
    } catch (error) {
        showToast(error.message, true);
    }
}

function addressPart(result, type) {
    const part = result.address_components?.find((component) => component.types.includes(type));
    return part ? part.long_name : "";
}

function reverseGeocodeStorePosition(lat, lng) {
    if (!window.google?.maps?.Geocoder) return;
    const geocoder = new google.maps.Geocoder();
    const form = document.getElementById("store-form");
    const status = document.getElementById("store-gps-status");
    const capture = storeLocationCapture;
    geocoder.geocode({ location: { lat, lng } }, (results, geoStatus) => {
        if (storeLocationCapture !== capture) return;
        if (geoStatus !== "OK" || !results?.length) {
            if (status) status.textContent = `${storeLocationMessage} Completa la direccion manualmente.`;
            return;
        }
        const best = results[0];
        if (!form.address.value) form.address.value = best.formatted_address || "";
        if (!form.municipality.value) {
            form.municipality.value =
                addressPart(best, "locality") ||
                addressPart(best, "administrative_area_level_2") ||
                addressPart(best, "administrative_area_level_1");
        }
        if (!form.neighborhood.value) {
            form.neighborhood.value =
                addressPart(best, "neighborhood") ||
                addressPart(best, "sublocality") ||
                addressPart(best, "sublocality_level_1");
        }
        if (status) status.textContent = `${storeLocationMessage} Direccion detectada; revisala antes de guardar.`;
    });
}

async function onStoreSubmit(event) {
    event.preventDefault();
    const form = event.currentTarget;
    if (storeLocationCapture?.accuracy_m > 100 && !confirm("La precision supera los 100 metros. ?Verificaste que las coordenadas corresponden a la tienda y deseas guardarlas?")) return;
    const payload = {
        name: form.elements.namedItem("name").value.trim(),
        contact_name: form.contact_name.value.trim(),
        phone: form.phone.value.trim(),
        municipality: form.municipality.value.trim(),
        neighborhood: form.neighborhood.value.trim(),
        department_id: Number(form.department_id.value),
        product_type: form.product_type.value,
        visit_frequency: form.visit_frequency.value,
        address: form.address.value.trim(),
        reference: form.reference.value.trim(),
        latitude: Number(form.latitude.value),
        longitude: Number(form.longitude.value),
        accuracy_m: storeLocationCapture?.accuracy_m ?? null,
        captured_at: storeLocationCapture?.captured_at ?? null,
        is_active: form.is_active.checked
    };
    try {
        if (editingStoreId && !navigator.onLine) {
            showToast("Conectate a internet para editar una tienda existente.", true);
            return;
        }
        const response = editingStoreId
            ? await postJson(`/api/stores/${editingStoreId}/`, payload)
            : await postJsonOrQueue(API.stores, payload, "Registrar tienda");
        form.reset();
        const status = document.getElementById("store-gps-status");
        if (status) status.textContent = "";
        storeLocationCapture = null;
        editingStoreId = null;
        document.getElementById("store-submit").textContent = "Guardar tienda";
        document.getElementById("btn-cancel-store-edit").style.display = "none";
        if (response.queued) {
            showToast("Tienda guardada sin conexion. Se sincronizara despues.");
            return;
        }
        showToast("Tienda guardada con GPS.");
        await reloadAll();
        if (window.google?.maps) focusStoreById(response.store.id);
    } catch (error) {
        showToast(error.message, true);
    }
}

function onOrderStoreChange(event) {
    const storeId = Number(event.target.value || 0);
    const destination = document.getElementById("order-destination");
    if (!storeId || !destination) {
        if (destination) destination.disabled = false;
        return;
    }
    const store = state.stores.find((item) => item.id === storeId);
    if (!store) return;
    destination.value = String(store.department_id);
    destination.disabled = true;
}

function onStoresActionClick(event) {
    const editButton = event.target.closest("button[data-edit-store]");
    if (editButton) {
        editStore(Number(editButton.dataset.editStore));
        return;
    }
    const button = event.target.closest("button[data-focus-store]");
    if (!button) return;
    focusStoreById(Number(button.dataset.focusStore));
}

function renderPaymentTripSelect() {
    const select = document.getElementById("payment-trip");
    if (!select) return;
    const previous = select.value;
    const trips = state.trips.filter(trip => ["planned", "in_progress"].includes(trip.status));
    select.innerHTML = '<option value="">Cobro fuera de ruta</option>'
        + trips.map(trip => `<option value="${trip.id}">${escapeHtml(trip.code)} - ${escapeHtml(trip.driver_name || "Sin repartidor")}</option>`).join("");
    if (previous && trips.some(trip => String(trip.id) === previous)) select.value = previous;
    select.required = state.currentUser?.role === "driver";
    if (select.required && !select.value && trips.length === 1) select.value = String(trips[0].id);
}

function editStore(storeId) {
    const store = state.stores.find(item => item.id === storeId);
    if (!store) return;
    const form = document.getElementById("store-form");
    for (const name of ["name", "contact_name", "phone", "municipality", "neighborhood", "product_type", "visit_frequency", "address", "reference", "latitude", "longitude"]) {
        if (form.elements[name]) form.elements[name].value = store[name] ?? "";
    }
    form.department_id.value = String(store.department_id);
    form.is_active.checked = store.is_active;
    storeLocationCapture = store.location_captured_at ? {
        latitude: store.latitude,
        longitude: store.longitude,
        accuracy_m: store.location_accuracy_m,
        captured_at: store.location_captured_at,
    } : null;
    editingStoreId = store.id;
    document.getElementById("store-submit").textContent = "Guardar cambios";
    document.getElementById("btn-cancel-store-edit").style.display = "";
    document.getElementById("store-form-card").scrollIntoView({ behavior: "smooth", block: "start" });
}

function cancelStoreEdit() {
    editingStoreId = null;
    storeLocationCapture = null;
    const form = document.getElementById("store-form");
    form.reset();
    document.getElementById("store-submit").textContent = "Guardar tienda";
    document.getElementById("btn-cancel-store-edit").style.display = "none";
    document.getElementById("store-gps-status").textContent = "";
}

function focusStoreById(storeId) {
    const store = state.stores.find((item) => item.id === storeId);
    if (!store || !store.latitude || !store.longitude) {
        showToast("Esta tienda no tiene coordenadas GPS validas.", true);
        return;
    }
    document.querySelector('[data-tab="map"]')?.click();
    if (!map) renderMap();
    const position = { lat: Number(store.latitude), lng: Number(store.longitude) };
    map.setZoom(17);
    map.panTo(position);
    const marker = gmapStoreMarkers.find((item) => item.storeId === storeId);
    if (marker) {
        google.maps.event.trigger(marker, "click");
    }
}

async function onDriverSubmit(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const payload = {
        name: form.name.value.trim(),
        phone: form.phone.value.trim(),
        license_number: form.license_number.value.trim(),
        is_active: form.is_active.checked
    };
    try {
        await postJson(API.drivers, payload);
        form.reset();
        showToast("Repartidor registrado.");
        await reloadAll();
    } catch (error) {
        showToast(error.message, true);
    }
}

async function onProductSubmit(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const payload = {
        name: form.name.value.trim(),
        product_type: form.product_type.value,
        presentation: form.presentation.value.trim(),
        unit_price: Number(form.unit_price.value),
        unit_weight_kg: Number(form.unit_weight_kg.value),
        is_active: form.is_active.checked
    };
    try {
        await postJson(API.products, payload);
        form.reset();
        form.is_active.checked = true;
        form.unit_weight_kg.value = "1.00";
        showToast("Producto registrado.");
        await reloadAll();
    } catch (error) {
        showToast(error.message, true);
    }
}

async function onOrderSubmit(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const product = state.products.find((item) => String(item.id) === form.product_id.value);
    if (!product) {
        showToast("Selecciona un producto.", true);
        return;
    }
    const quantity = Number(form.quantity.value || 0);
    const payload = {
        origin_id: Number(form.origin_id.value),
        destination_id: Number(form.destination_id.value),
        store_id: form.store_id.value ? Number(form.store_id.value) : null,
        weight_kg: Number(form.weight_kg.value || product.unit_weight_kg),
        package_count: quantity,
        items: [{
            product_id: product.id,
            quantity,
            unit_price: product.unit_price
        }],
        priority: form.priority.value
    };
    const departureLatitude = form.departure_latitude.value;
    const departureLongitude = form.departure_longitude.value;
    if (Boolean(departureLatitude) !== Boolean(departureLongitude)) {
        showToast("Completa latitud y longitud de salida, o deja ambas vacias.", true);
        return;
    }
    if (orderDepartureCapture?.accuracy_m > 100 && !confirm("La precision de la salida supera los 100 metros. ¿Deseas guardarla de todos modos?")) return;
    if (departureLatitude) {
        Object.assign(payload, {
            departure_latitude: Number(departureLatitude),
            departure_longitude: Number(departureLongitude),
            ...(orderDepartureCapture ? {
                departure_accuracy_m: orderDepartureCapture.accuracy_m,
                departure_captured_at: orderDepartureCapture.captured_at
            } : {})
        });
    }
    try {
        const response = await postJsonOrQueue(API.orders, payload, "Crear entrega");
        form.reset();
        orderDepartureCapture = null;
        document.getElementById("order-departure-status").textContent = "";
        form.destination_id.disabled = false;
        showToast(response.queued ? "Entrega guardada sin conexion. Se sincronizara despues." : "Entrega creada.");
        if (response.queued) {
            updateOrderEstimate();
            return;
        }
        await reloadAll();
    } catch (error) {
        showToast(error.message, true);
    }
}

async function onPaymentSubmit(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const payload = {
        store_id: Number(form.store_id.value),
        order_id: form.order_id.value ? Number(form.order_id.value) : null,
        amount: Number(form.amount.value),
        payment_type: form.payment_type.value,
        method: form.method.value,
        note: form.note.value.trim(),
        trip_id: form.trip_id.value ? Number(form.trip_id.value) : null,
        sync_status: navigator.onLine ? "synced" : "pending",
        driver_id: form.driver_id.value ? Number(form.driver_id.value) : null,
        uuid: makeLocalId()
    };
    try {
        const response = await postJsonOrQueue(API.payments, payload, "Registrar cobro");
        form.reset();
        showToast(response.queued ? "Cobro guardado sin conexion. Se sincronizara despues." : "Cobro registrado.");
        if (response.queued) return;
        await reloadAll();
    } catch (error) {
        showToast(error.message, true);
    }
}

async function reloadReport() {
    try {
        const params = [];
        const from = document.getElementById("report-date-from").value;
        const to = document.getElementById("report-date-to").value;
        if (from) params.push(`date_from=${from}`);
        if (to) params.push(`date_to=${to}`);
        const res = await getJson(params.length ? `${API.reports}?${params.join("&")}` : API.reports);
        state.report = res.report;
        renderReport();
    } catch (error) {
        showToast(error.message, true);
    }
}

async function onPlannerSubmit(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const selectedOrders = Array.from(
        document.querySelectorAll("#planner-orders-list input[name='order_ids']:checked")
    ).map((node) => Number(node.value));
    if (!selectedOrders.length) {
        showToast("Selecciona al menos una entrega.", true);
        return;
    }
    if (selectedOrders.some(id => id < 0) || !navigator.onLine) {
        showToast("Conectate y sincroniza los pedidos antes de planificar la ruta. Las entregas y los cobros de rutas descargadas se pueden registrar sin conexion.", true);
        return;
    }
    const vehicleId = Number(form.vehicle_id.value);
    if (!vehicleId) {
        showToast("Selecciona un vehiculo.", true);
        return;
    }
    const driverId = form.driver_id.value ? Number(form.driver_id.value) : null;
    try {
        const response = await postJson(API.planTrip, {
            vehicle_id: vehicleId,
            driver_id: driverId,
            order_ids: selectedOrders,
            algorithm: form.algorithm.value
        });
        showPlannerResult(response.trip);
        showToast("Ruta planificada correctamente.");
        await reloadAll();
    } catch (error) {
        showToast(error.message, true);
    }
}

async function onTripsActionClick(event) {
    const simulateButton = event.target.closest("button[data-simulate-delivery]");
    if (simulateButton) {
        await simulateDelivery(Number(simulateButton.dataset.tripId));
        return;
    }

    const button = event.target.closest("button[data-action]");
    if (!button) return;
    const tripId = Number(button.dataset.tripId);
    const action = button.dataset.action;
    const trip = state.trips.find(row => row.id === tripId);
    if (action === "complete" && trip?.stops?.some(stop => stop.status === "pending")) {
        showToast("Registra cada parada como entregada o no entregada antes de completar la ruta.", true);
        return;
    }
    try {
        const response = await postJsonOrQueue(`/api/trips/${tripId}/action/`, { action }, `Ruta: ${statusLabel(action)}`);
        showToast(response.queued ? `Accion "${action}" guardada sin conexion.` : `Accion "${action}" ejecutada.`);
        if (response.queued) return;
        await reloadAll();
    } catch (error) {
        showToast(error.message, true);
    }
}

async function onEventSubmit(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const tripId = Number(form.trip_id.value);
    const note = form.note.value.trim();
    if (!tripId || !note) {
        showToast("Debes seleccionar una ruta y escribir el registro.", true);
        return;
    }
    try {
        const response = await postJsonOrQueue(`/api/trips/${tripId}/events/`, { note }, "Registrar visita");
        form.reset();
        showToast(response.queued ? "Visita guardada sin conexion. Se sincronizara despues." : "Evento registrado.");
        if (response.queued) return;
        await reloadAll();
    } catch (error) {
        showToast(error.message, true);
    }
}

async function onDepartmentSubmit(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const payload = {
        code: form.code.value.trim(),
        name: form.name.value.trim(),
        latitude: form.latitude.value !== "" ? Number(form.latitude.value) : null,
        longitude: form.longitude.value !== "" ? Number(form.longitude.value) : null,
    };
    try {
        await postJson(API.departments, payload);
        form.reset();
        showToast("Zona registrada.");
        await reloadAll();
    } catch (error) {
        showToast(error.message, true);
    }
}

async function onUserSubmit(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const payload = {
        username: form.username.value.trim(),
        password: form.password.value,
        first_name: form.first_name.value.trim(),
        last_name: form.last_name.value.trim(),
        email: form.email.value.trim(),
        phone: form.phone.value.trim(),
        license_number: form.license_number.value.trim(),
        role: form.role.value
    };
    try {
        await postJson(API.users, payload);
        form.reset();
        showToast("Usuario creado.");
        const res = await getJson(API.users);
        state.users = res.users;
        renderUsers();
        renderPendingUsers();
        renderBusinessDetails();
    } catch (error) {
        showToast(error.message, true);
    }
}

// â”€â”€ DISPLAY â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

function showPlannerResult(trip) {
    const box = document.getElementById("planner-result");
    const fuelCostLine = trip.estimated_fuel_cost_gtq != null
        ? `<p><strong>Costo de combustible:</strong> Q ${trip.estimated_fuel_cost_gtq.toFixed(2)} <small>(Q ${trip.fuel_price_gtq_gal?.toFixed(2)}/gal al momento)</small></p>`
        : "";
    box.innerHTML = `
        <h3>Resultado de planificacion</h3>
        <p><strong>Codigo:</strong> ${escapeHtml(trip.code)}</p>
        <p><strong>Vehiculo:</strong> ${escapeHtml(trip.vehicle_plate)}</p>
        <p><strong>Repartidor:</strong> ${escapeHtml(trip.driver_name || "No asignado")}</p>
        <p><strong>Recorrido sugerido:</strong> ${escapeHtml(trip.route_nodes.join(" -> "))}</p>
        <p><strong>Distancia:</strong> ${trip.total_distance_km.toFixed(2)} km</p>
        <p><strong>Combustible estimado:</strong> ${trip.estimated_fuel_gallons.toFixed(2)} galones</p>
        ${fuelCostLine}
        <p><strong>Cobro/costo estimado:</strong> Q ${trip.estimated_cost.toFixed(2)}</p>
        <p><strong>Entregas asociadas:</strong> ${trip.orders.length}</p>
    `;
}

function buildTripActions(trip) {
    const role = state.currentUser ? state.currentUser.role : "seller";
    if (role === "seller") return "—";
    if (trip.status === "completed" || trip.status === "canceled") return "Sin acciones";
    if (role === "driver") {
        if (trip.status === "planned") return `<button class="btn-inline" data-action="start" data-trip-id="${trip.id}">Iniciar mi ruta</button>`;
        return `<button class="btn-inline btn-neutral" data-action="complete" data-trip-id="${trip.id}">Completar mi ruta</button>`;
    }
    const simButton = `<button class="btn-inline btn-neutral" data-simulate-delivery="1" data-trip-id="${trip.id}">Simular entrega</button>`;
    if (trip.status === "planned") {
        return `
            <button class="btn-inline" data-action="start" data-trip-id="${trip.id}">Iniciar</button>
            ${simButton}
            <button class="btn-inline btn-danger" data-action="cancel" data-trip-id="${trip.id}">Cancelar</button>
        `;
    }
    return `
        <button class="btn-inline btn-neutral" data-action="complete" data-trip-id="${trip.id}">Completar</button>
        ${simButton}
        <button class="btn-inline btn-danger" data-action="cancel" data-trip-id="${trip.id}">Cancelar</button>
    `;
}

// â”€â”€ CHART â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

function drawBarChart(canvasId, labels, values, color) {
    const canvas = document.getElementById(canvasId);
    const ctx = canvas.getContext("2d");
    const width = canvas.width;
    const height = canvas.height;
    ctx.clearRect(0, 0, width, height);

    if (!labels.length || !values.length) {
        ctx.fillStyle = "#3f5367";
        ctx.font = "14px Trebuchet MS";
        ctx.fillText("Sin datos para mostrar.", 12, 26);
        return;
    }

    const padding = { top: 20, right: 20, bottom: 58, left: 36 };
    const graphWidth = width - padding.left - padding.right;
    const graphHeight = height - padding.top - padding.bottom;
    const maxValue = Math.max(...values, 1);
    const barWidth = (graphWidth / values.length) * 0.66;

    ctx.strokeStyle = "rgba(19, 33, 58, 0.24)";
    ctx.beginPath();
    ctx.moveTo(padding.left, padding.top);
    ctx.lineTo(padding.left, padding.top + graphHeight);
    ctx.lineTo(padding.left + graphWidth, padding.top + graphHeight);
    ctx.stroke();

    values.forEach((value, index) => {
        const x = padding.left + (index * graphWidth) / values.length + (graphWidth / values.length - barWidth) / 2;
        const barHeight = (value / maxValue) * graphHeight;
        const y = padding.top + graphHeight - barHeight;

        ctx.fillStyle = color;
        ctx.fillRect(x, y, barWidth, barHeight);

        ctx.fillStyle = "#10273f";
        ctx.font = "12px Trebuchet MS";
        ctx.fillText(String(value), x, y - 6);

        const label = labels[index].replaceAll("_", " ");
        ctx.save();
        ctx.translate(x + barWidth / 2, height - 14);
        ctx.rotate(-0.42);
        ctx.textAlign = "right";
        ctx.fillStyle = "#3a5369";
        ctx.fillText(label, 0, 0);
        ctx.restore();
    });
}

// â”€â”€ HTTP â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

async function refreshOfflineSummary() {
    try {
        const account = await FlamiaOffline.read();
        offlinePendingCount = account.queue.length;
        offlineLastError = account.queue.find(item => item.error)?.error || (account.queue.length ? offlineLastError : "");
        const list = document.getElementById("offline-pending-list");
        if (list) list.innerHTML = account.queue.map(item => `<li>${escapeHtml(item.label)} ? ${escapeHtml(new Date(item.created_at).toLocaleString("es-GT"))}${item.error ? `: ${escapeHtml(item.error)}` : ""}
            <button type="button" data-remove-pending="${escapeHtml(item.id)}">Descartar</button></li>`).join("");
        const legacy = localStorage.getItem(OFFLINE_QUEUE_KEY);
        if (legacy && JSON.parse(legacy).length) offlineLastError = "Hay pendientes de la version anterior. Descargalos antes de cambiar de dispositivo.";
    } catch (error) { offlineLastError = error.message; }
    renderOfflineStatus();
}

function makeLocalId() { return FlamiaOffline.uuid(); }

function isNetworkError(error) { return error.network === true || error instanceof TypeError || error.name === "AbortError"; }

async function postJsonOrQueue(url, payload, label) {
    // Save first: a reload or a lost response must not lose the operation's key.
    const item = await FlamiaOffline.enqueue(url, payload, label);
    if (navigator.storage?.persist) navigator.storage.persist().catch(() => {});
    await refreshOfflineSummary();
    let responses = {};
    if (navigator.onLine) responses = await flushOfflineQueue();
    await reloadAll();
    return responses[item.id] || { ok: true, queued: true, local_id: item.local_id };
}

async function flushOfflineQueue() {
    const responses = {};
    await FlamiaOffline.lock(async () => {
        isSyncingOfflineQueue = true;
        offlineLastError = "";
        renderOfflineStatus("Sincronizando...");
        try {
            // Do not replay another user's records after a session switch.
            const me = await requestJson(API.me);
            if (String(me.user.id) !== FlamiaOffline.owner) throw new Error("La sesion cambio. Recarga e inicia sesion con la cuenta de estos pendientes.");
            while (true) {
                const account = await FlamiaOffline.read();
                const item = account.queue[0];
                if (!item) break;
                try {
                    const payload = FlamiaOffline.resolvePayload(item.payload, account.mappings);
                    const response = await postJson(FlamiaOffline.resolveUrl(item.url, account.mappings), payload, item.id);
                    await FlamiaOffline.acknowledge(item, response);
                    responses[item.id] = response;
                } catch (error) {
                    await FlamiaOffline.setError(item.id, error.message);
                    throw error;
                }
            }
        } catch (error) {
            offlineLastError = error.message;
        } finally {
            isSyncingOfflineQueue = false;
            await refreshOfflineSummary();
        }
    });
    return responses;
}

async function syncPendingData() {
    if (isSyncingOfflineQueue || !navigator.onLine) return;
    await refreshOfflineSummary();
    if (!offlinePendingCount) return;
    await flushOfflineQueue();
    await reloadAll();
}

function renderOfflineStatus(detailOverride = "") {
    const banner = document.getElementById("offline-banner");
    const label = document.getElementById("offline-state-label");
    const detail = document.getElementById("offline-state-detail");
    const syncButton = document.getElementById("btn-sync-now");
    const online = navigator.onLine;
    banner?.classList.toggle("is-offline", !online || !!offlinePendingCount);
    if (label) label.textContent = isSyncingOfflineQueue ? "Sincronizando" : !online ? "Sin conexion" : offlinePendingCount ? "Pendientes de envio" : "En linea";
    if (detail) detail.textContent = detailOverride || offlineLastError || (offlinePendingCount ? `${offlinePendingCount} operacion(es) guardadas en este dispositivo.` : "Sin pendientes de envio. Los datos offline son la ultima copia descargada.");
    if (syncButton) syncButton.disabled = !online || !offlinePendingCount || isSyncingOfflineQueue;
}

async function requestJson(url, payload, operationId) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 25000);
    try {
        const response = await fetch(url, {
            method: payload === undefined ? "GET" : "POST",
            credentials: "same-origin", cache: "no-store", signal: controller.signal,
            headers: payload === undefined ? { "X-Flamia-User-ID": FlamiaOffline.owner } : {
                "Content-Type": "application/json", "X-CSRFToken": getCookie("csrftoken"),
                "X-Flamia-User-ID": FlamiaOffline.owner,
                ...(operationId ? { "Idempotency-Key": operationId } : {})
            },
            ...(payload === undefined ? {} : { body: JSON.stringify(payload) })
        });
        if (response.redirected || response.status === 401) throw new Error("Tu sesion vencio. Inicia sesion con la misma cuenta para sincronizar; tus pendientes siguen guardados.");
        if (response.status === 403) throw new Error("No tienes permiso o la sesion necesita renovarse. Inicia sesion nuevamente; los pendientes siguen guardados.");
        if (response.status >= 500) {
            const error = new Error("El servidor no esta disponible. Los pendientes se reintentaran automaticamente.");
            error.network = true; throw error;
        }
        let data;
        try { data = await response.json(); }
        catch (_) { throw new Error("El servidor no devolvio una respuesta valida. Los pendientes siguen guardados."); }
        if (!response.ok || !data.ok) throw new Error(data.error || `Error en ${url}`);
        return data;
    } catch (error) {
        if (error.name === "AbortError" || error instanceof TypeError) {
            const networkError = new Error("No se pudo conectar con el servidor. La operacion permanece guardada para reintentar.");
            networkError.network = true;
            throw networkError;
        }
        throw error;
    } finally { clearTimeout(timeout); }
}

async function getJson(url) {
    let data;
    try { data = await requestJson(url); }
    catch (error) {
        if (!isNetworkError(error)) throw error;
        return FlamiaOffline.projected(url);
    }
    try { await FlamiaOffline.saveSnapshot(url, data); }
    catch (error) { offlineLastError = error.message; renderOfflineStatus(); return data; }
    return FlamiaOffline.projected(url, data);
}

async function postJson(url, payload, operationId) {
    return requestJson(url, payload, operationId);
}

function statusLabel(status) {
    const labels = {
        pending: "Pendiente", assigned: "Asignado", in_transit: "En ruta",
        delivered: "Entregado", not_delivered: "No entregado", canceled: "Cancelado",
        planned: "Planificado", in_progress: "En progreso", completed: "Completado",
        start: "Iniciar", complete: "Completar", cancel: "Cancelar"
    };
    return labels[status] || status;
}

function priorityLabel(priority) {
    const labels = { low: "Baja", normal: "Normal", high: "Alta" };
    return labels[priority] || priority;
}

function productTypeLabel(productType) {
    const labels = { water: "Agua", gas: "Gas", both: "Agua y gas" };
    return labels[productType] || productType;
}

function visitFrequencyLabel(value) {
    const labels = { on_demand: "Bajo pedido", weekly: "Semanal", biweekly: "Quincenal", monthly: "Mensual" };
    return labels[value] || value || "Bajo pedido";
}

function paymentTypeLabel(paymentType) {
    const labels = { full_payment: "Pago completo", partial_payment: "Abono", credit: "Credito" };
    return labels[paymentType] || paymentType;
}

function paymentMethodLabel(method) {
    const labels = { cash: "Efectivo", transfer: "Transferencia", other: "Otro" };
    return labels[method] || method;
}

function statusChip(status) {
    if (status === "active") return `<span class="status-chip status-completed">Activo</span>`;
    if (status === "inactive") return `<span class="status-chip status-canceled">Inactivo</span>`;
    return `<span class="status-chip status-${status}">${escapeHtml(statusLabel(status))}</span>`;
}

function setText(id, value) {
    const node = document.getElementById(id);
    if (node) node.textContent = String(value);
}

function getCookie(name) {
    const cookies = document.cookie ? document.cookie.split(";") : [];
    for (const cookie of cookies) {
        const [rawName, ...rest] = cookie.trim().split("=");
        if (rawName === name) return decodeURIComponent(rest.join("="));
    }
    return "";
}

function showToast(message, isError = false) {
    const toast = document.getElementById("toast");
    toast.textContent = message;
    toast.style.background = isError ? "rgba(127, 29, 29, 0.96)" : "rgba(15, 23, 42, 0.95)";
    toast.classList.add("show");
    window.setTimeout(() => toast.classList.remove("show"), 2400);
}

function escapeHtml(value) {
    return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}
