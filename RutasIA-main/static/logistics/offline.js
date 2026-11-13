/* Durable, account-scoped outbox. No operation is acknowledged before IDB commits. */
(() => {
    "use strict";
    const owner = document.body.dataset.userId;
    let database;
    const open = () => database ||= new Promise((resolve, reject) => {
        const request = indexedDB.open("flamia-offline-v2", 1);
        request.onupgradeneeded = () => request.result.createObjectStore("accounts");
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(new Error("No se pudo abrir el almacenamiento offline. Revisa el espacio y los permisos del navegador."));
        request.onblocked = () => reject(new Error("Cierra otras pestañas de Flamia y vuelve a intentarlo."));
    });
    async function access(change) {
        const db = await open();
        return new Promise((resolve, reject) => {
            const tx = db.transaction("accounts", change ? "readwrite" : "readonly");
            const store = tx.objectStore("accounts");
            const request = store.get(owner);
            let result;
            request.onsuccess = () => {
                const account = request.result || { queue: [], snapshots: {}, mappings: {}, sequence: 0 };
                try {
                    result = change ? change(account) : account;
                    if (change) store.put(account, owner);
                } catch (error) { reject(error); tx.abort(); }
            };
            tx.oncomplete = () => resolve(result);
            tx.onabort = tx.onerror = () => reject(new Error("No se pudo guardar en este dispositivo. No cierres el formulario; revisa el espacio disponible."));
        });
    }
    function uuid() {
        const bytes = crypto.getRandomValues(new Uint8Array(16));
        bytes[6] = (bytes[6] & 15) | 64;
        bytes[8] = (bytes[8] & 63) | 128;
        const hex = [...bytes].map(value => value.toString(16).padStart(2, "0")).join("");
        return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
    }
    function resolvePayload(payload, mappings) {
        const copy = { ...payload };
        for (const key of ["store_id", "order_id", "trip_id"]) {
            if (copy[key] < 0) {
                if (!mappings[copy[key]]) throw new Error("La operacion depende de otro registro pendiente de sincronizar.");
                copy[key] = mappings[copy[key]];
            }
        }
        return copy;
    }
    function resolveUrl(url, mappings) {
        return url.replace(/\/orders\/(-\d+)\/action\//, (_, id) => {
            if (!mappings[id]) throw new Error("Sincroniza primero el pedido del que depende esta accion.");
            return `/orders/${mappings[id]}/action/`;
        });
    }
    const rows = (snapshots, url, key) => snapshots[url]?.[key] || [];
    function apply(snapshots, item, response, mappings = {}) {
        const p = { ...item.payload };
        for (const key of ["store_id", "order_id", "trip_id"]) p[key] = mappings[p[key]] || p[key];
        const id = response?.store?.id || response?.order?.id || response?.payment?.id || item.local_id;
        const stamp = item.created_at;
        const insert = (url, key, value) => {
            snapshots[url] ||= { ok: true, [key]: [] };
            const list = snapshots[url][key];
            const index = list.findIndex(row => row.id === value.id || row.id === item.local_id || (value.uuid && row.uuid === value.uuid));
            if (index < 0) list.unshift(value); else list[index] = value;
        };
        if (item.url === "/api/stores/") {
            const department = rows(snapshots, "/api/departments/", "departments").find(row => row.id === p.department_id);
            insert(item.url, "stores", response?.store || { ...p, id, department_name: department?.name || "", balance_due: 0, offline_pending: true });
        } else if (item.url === "/api/orders/") {
            const store = rows(snapshots, "/api/stores/", "stores").find(row => row.id === p.store_id);
            const departments = rows(snapshots, "/api/departments/", "departments");
            const products = rows(snapshots, "/api/products/", "products");
            const items = (p.items || []).map(line => ({ ...line, subtotal: line.quantity * Math.round(line.unit_price * 100) / 100,
                product_name: products.find(product => product.id === line.product_id)?.name || "" }));
            const total = items.reduce((sum, line) => sum + Math.round(line.subtotal * 100), 0) / 100;
            const inventory = rows(snapshots, "/api/inventory/", "inventory");
            for (const line of items) {
                const stock = inventory.find(row => row.product_id === line.product_id);
                if (stock) stock.quantity = Math.max(0, stock.quantity - line.quantity);
            }
            insert(item.url, "orders", response?.order || { ...p, id, code: `PENDIENTE-${Math.abs(id)}`, status: "pending", items,
                origin_name: departments.find(row => row.id === p.origin_id)?.name || "",
                destination_name: store?.department_name || departments.find(row => row.id === p.destination_id)?.name || "",
                destination_id: store?.department_id || p.destination_id, store_name: store?.name,
                store_latitude: store?.latitude, store_longitude: store?.longitude,
                total_amount: total, paid_amount: 0, balance_due: total, requested_for: stamp, offline_pending: true });
        } else if (item.url === "/api/payments/") {
            const order = rows(snapshots, "/api/orders/", "orders").find(row => row.id === p.order_id);
            const payment = response?.payment || { ...p, id, created_at: stamp, occurred_at: p.occurred_at || stamp, sync_status: "pending",
                recorded_by_name: snapshots["/api/me/"]?.user?.full_name || snapshots["/api/me/"]?.user?.username,
                driver_name: rows(snapshots, "/api/drivers/", "drivers").find(driver => driver.id === p.driver_id)?.name,
                store_name: rows(snapshots, "/api/stores/", "stores").find(row => row.id === p.store_id)?.name,
                order_code: order?.code, offline_pending: true };
            const exists = rows(snapshots, item.url, "payments").some(row => row.uuid === p.uuid);
            insert(item.url, "payments", payment);
            if (!exists && p.payment_type !== "credit") {
                let remaining = Math.round(Number(p.amount) * 100);
                const targets = order ? [order] : rows(snapshots, "/api/orders/", "orders")
                    .filter(row => row.store_id === p.store_id && row.status !== "canceled")
                    .sort((a, b) => String(a.requested_for || a.created_at).localeCompare(String(b.requested_for || b.created_at)) || a.id - b.id);
                for (const target of targets) {
                    const applied = Math.min(remaining, Math.round(target.balance_due * 100));
                    target.paid_amount = (Math.round(target.paid_amount * 100) + applied) / 100;
                    target.balance_due = Math.max(0, Math.round(target.total_amount * 100) - Math.round(target.paid_amount * 100)) / 100;
                    remaining -= applied;
                    if (remaining <= 0) break;
                }
            }
        } else if (/^\/api\/orders\/-?\d+\/action\/$/.test(item.url)) {
            const localId = Number(item.url.split("/")[3]);
            const orderId = mappings[localId] || localId;
            const order = rows(snapshots, "/api/orders/", "orders").find(row => row.id === orderId);
            if (order && order.status !== "canceled") {
                const inventory = rows(snapshots, "/api/inventory/", "inventory");
                for (const line of order.items || []) {
                    const stock = inventory.find(row => row.product_id === line.product_id);
                    if (stock) stock.quantity += line.quantity;
                }
            }
            if (order) Object.assign(order, response?.order || { status: "canceled", balance_due: 0 });
            for (const trip of rows(snapshots, "/api/trips/", "trips")) {
                for (const value of trip.orders) if (value.id === orderId) Object.assign(value, { status: "canceled", balance_due: 0 });
                for (const stop of trip.stops) if (stop.order_id === orderId && stop.status !== "delivered") {
                    Object.assign(stop, { status: "not_delivered", observation: "Pedido cancelado por el responsable de la ruta." });
                }
            }
        } else {
            const match = item.url.match(/^\/api\/trips\/(\d+)\/(stops\/(\d+)\/|action\/|events\/)$/);
            const trip = match && rows(snapshots, "/api/trips/", "trips").find(row => row.id === Number(match[1]));
            if (!trip) return;
            if (response?.trip) {
                Object.assign(trip, response.trip);
                for (const value of trip.orders) {
                    const order = rows(snapshots, "/api/orders/", "orders").find(row => row.id === value.id);
                    if (order) Object.assign(order, value);
                }
            }
            else if (match[3]) {
                const stop = trip.stops.find(row => row.id === Number(match[3]));
                if (stop) {
                    Object.assign(stop, response?.stop || { ...p, delivered_at: p.status === "delivered" ? stamp : null, offline_pending: true });
                    const order = rows(snapshots, "/api/orders/", "orders").find(row => row.id === stop.order_id);
                    if (order && p.status !== "pending") order.status = p.status === "delivered" ? "delivered" : "pending";
                    const tripOrder = trip.orders.find(row => row.id === stop.order_id);
                    if (tripOrder && order) tripOrder.status = order.status;
                    const event = response?.event || { id: item.local_id, stop_id: stop.id, occurred_at: p.occurred_at || stamp,
                        created_at: stamp, note: p.observation || "Resultado de visita registrado sin conexion",
                        recorded_by_name: snapshots["/api/me/"]?.user?.full_name || snapshots["/api/me/"]?.user?.username, offline_pending: true };
                    trip.events = trip.events.filter(row => row.id !== item.local_id && row.id !== event.id);
                    trip.events.unshift(event);
                }
            } else if (p.action) {
                trip.status = { start: "in_progress", complete: "completed", cancel: "canceled" }[p.action] || trip.status;
                for (const value of trip.orders) {
                    const failed = trip.stops.some(stop => stop.order_id === value.id && stop.status === "not_delivered");
                    if (p.action === "start" && !["delivered", "canceled"].includes(value.status)) value.status = "in_transit";
                    if (p.action === "complete" && !failed && value.status !== "canceled") value.status = "delivered";
                    if (p.action === "cancel" && !["delivered", "canceled"].includes(value.status)) value.status = "pending";
                    const order = rows(snapshots, "/api/orders/", "orders").find(row => row.id === value.id);
                    if (order) order.status = value.status;
                }
            } else if (p.note && !trip.events.some(event => event.id === response?.event?.id)) {
                trip.events.unshift(response?.event || { id, note: p.note, created_at: stamp });
            }
        }
    }
    window.FlamiaOffline = {
        owner, uuid, resolvePayload, resolveUrl,
        read: () => access(),
        saveSnapshot: (url, data) => access(account => { account.snapshots[url] = data; }),
        async projected(url, fallback) {
            const account = await access();
            const snapshots = structuredClone(account.snapshots);
            if (fallback) snapshots[url] = structuredClone(fallback);
            for (const item of account.queue) apply(snapshots, item, null, account.mappings);
            for (const order of rows(snapshots, "/api/orders/", "orders")) {
                order.payment_status = order.total_amount > 0 && order.paid_amount >= order.total_amount ? "paid" : order.paid_amount > 0 ? "partial" : "pending";
            }
            if (url === "/api/balances/" && account.queue.length) {
                const balances = {};
                for (const order of rows(snapshots, "/api/orders/", "orders")) {
                    if (!order.store_id || order.status === "canceled") continue;
                    const store = rows(snapshots, "/api/stores/", "stores").find(row => row.id === order.store_id);
                    balances[order.store_id] ||= { store_id: order.store_id, store_name: store?.name || order.store_name,
                        municipality: store?.municipality || "", neighborhood: store?.neighborhood || "",
                        sales_total: 0, paid_total: 0, balance_due: 0 };
                    const row = balances[order.store_id];
                    row.sales_total += order.total_amount;
                    row.paid_total += order.paid_amount;
                    row.balance_due += order.balance_due;
                }
                for (const row of Object.values(balances)) for (const field of ["sales_total", "paid_total", "balance_due"]) row[field] = Math.round(row[field] * 100) / 100;
                snapshots[url] = { ok: true, balances: Object.values(balances).sort((a, b) => b.balance_due - a.balance_due) };
            }
            if (url === "/api/inventory/") {
                const inventory = rows(snapshots, url, "inventory");
                snapshots[url].summary = {
                    gas: inventory.filter(row => row.product_type === "gas" && row.is_active).reduce((sum, row) => sum + row.quantity, 0),
                    water: inventory.filter(row => row.product_type === "water" && row.is_active).reduce((sum, row) => sum + row.quantity, 0),
                    low_stock: inventory.filter(row => row.is_active && (row.quantity === 0 || (row.minimum_quantity > 0 && row.quantity <= row.minimum_quantity))).length
                };
            }
            const data = snapshots[url];
            if (!data) throw new Error("Estos datos todavia no estan disponibles sin conexion. Abre Flamia con internet antes de salir a repartir.");
            return data;
        },
        enqueue: (url, payload, label) => access(account => {
            const stamp = new Date().toISOString();
            const item = { id: uuid(), local_id: --account.sequence, url, payload: { ...payload, occurred_at: payload.occurred_at || stamp }, label, created_at: stamp };
            account.queue.push(item);
            return item;
        }),
        acknowledge: (item, response) => access(account => {
            const serverId = response.store?.id || response.order?.id || response.payment?.id;
            if (serverId) account.mappings[item.local_id] = serverId;
            apply(account.snapshots, item, response, account.mappings);
            account.queue = account.queue.filter(row => row.id !== item.id);
        }),
        remove: id => access(account => {
            const item = account.queue.find(row => row.id === id);
            if (!item) return;
            if (account.queue.some(row => [row.payload.store_id, row.payload.order_id, row.payload.trip_id].includes(item.local_id) || row.url === `/api/orders/${item.local_id}/action/`)) {
                throw new Error("Este pendiente tiene pedidos o cobros asociados. Revisa esos pendientes primero.");
            }
            account.queue = account.queue.filter(row => row.id !== id);
        }),
        setError: (id, error) => access(account => {
            const item = account.queue.find(row => row.id === id);
            if (item) item.error = error;
        }),
        async lock(work) {
            if (navigator.locks) return navigator.locks.request(`flamia-sync-${owner}`, { ifAvailable: true }, lock => lock ? work() : undefined);
            // Safari fallback: a lease acquired atomically in the same IDB store.
            const token = uuid();
            const acquired = await access(account => {
                if (account.lease?.until > Date.now()) return false;
                account.lease = { token, until: Date.now() + 60000 }; return true;
            });
            if (!acquired) return;
            const timer = setInterval(() => access(account => {
                if (account.lease?.token === token) account.lease.until = Date.now() + 60000;
            }).catch(() => {}), 10000);
            try { return await work(); }
            finally {
                clearInterval(timer);
                await access(account => { if (account.lease?.token === token) delete account.lease; });
            }
        }
    };
})();
