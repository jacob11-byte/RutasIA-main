/* Location capture is independent of the map and never substitutes a simulated fix. */
let storeLocationCapture = null;
let storeLocationMessage = "";
let deliveryLocationCapture = null;
const DELIVERY_GEOFENCE_METERS = 120;
const MAX_DELIVERY_ACCURACY_METERS = 100;
let arrivalDialogStopId = null;

function locationError(error) {
    if (error.code === 1) return "Ubicacion bloqueada. Permite la ubicacion para este sitio en el navegador. En iPhone: Ajustes > Privacidad y seguridad > Localizacion > Safari (o tu navegador); activa el acceso y Ubicacion precisa. Luego revisa el permiso de ubicacion del sitio y vuelve a pulsar el boton.";
    if (error.code === 3) return "Se agoto el tiempo para obtener ubicacion. Activa la localizacion del dispositivo, acercate a una ventana o sal al exterior y vuelve a intentarlo.";
    return "El dispositivo no pudo determinar su ubicacion. Activa la localizacion y vuelve a intentarlo. En computadora la precision depende del equipo y de su conexion.";
}

function captureDeviceLocation() {
    // Called directly from the click: no Permissions API dependency on Safari.
    return new Promise((resolve, reject) => {
        if (!window.isSecureContext) return reject(new Error("La ubicacion requiere HTTPS. Abre la direccion segura de Flamia; por HTTP desde otro equipo o telefono no se puede solicitar el permiso."));
        if (!navigator.geolocation) return reject(new Error("Este navegador no ofrece ubicacion. Abre Flamia en Safari, Chrome o Edge actualizado."));
        let best = null;
        let watchId;
        let settled = false;
        const finish = (error) => {
            if (settled) return;
            settled = true;
            clearTimeout(timer);
            if (watchId !== undefined) navigator.geolocation.clearWatch(watchId);
            if (best && error?.code !== 1) return resolve(best);
            reject(new Error(locationError(error || { code: 3 })));
        };
        const timer = setTimeout(() => finish({ code: 3 }), 35000);
        const success = (position) => {
            const { latitude, longitude, accuracy } = position.coords;
            if (!Number.isFinite(latitude) || !Number.isFinite(longitude) || !Number.isFinite(accuracy) || accuracy < 0) return;
            if (Math.abs(latitude) > 90 || Math.abs(longitude) > 180) return;
            // Reject stale fixes even if a browser ignores maximumAge.
            if (Date.now() - position.timestamp > 120000) return;
            if (!best || accuracy < best.accuracy_m) best = {
                latitude: Number(latitude.toFixed(6)), longitude: Number(longitude.toFixed(6)),
                // Store when the app received the fresh fix, using the same clock
                // as freshness checks and the UI (maximumAge is zero above).
                accuracy_m: accuracy, captured_at: new Date().toISOString()
            };
            if (accuracy <= 50) finish();
        };
        navigator.geolocation.getCurrentPosition(success, error => {
            if (error.code === 1) finish(error);
            else if (!settled) {
                // A fresh network fix can still work on a desktop or after GPS times out.
                navigator.geolocation.getCurrentPosition(success, finish,
                    { enableHighAccuracy: false, timeout: 12000, maximumAge: 0 });
            }
        }, { enableHighAccuracy: true, timeout: 18000, maximumAge: 0 });
        if (!settled) watchId = navigator.geolocation.watchPosition(success, error => {
            if (error.code === 1) finish(error);
        }, { enableHighAccuracy: true, timeout: 30000, maximumAge: 0 });
    });
}

function describeLocation(location) {
    const precision = Math.ceil(location.accuracy_m);
    return `Ubicacion capturada: precision aproximada de ${precision} m.${precision > 100 ? " Precision baja: comprueba que corresponde a la entrada de la tienda antes de guardar." : ""}`;
}

async function fillStoreGpsFromDevice() {
    const button = document.getElementById("btn-store-gps");
    const status = document.getElementById("store-gps-status");
    button.disabled = true;
    status.textContent = "Permite la ubicacion cuando el navegador lo solicite. Buscando una lectura precisa...";
    try {
        const location = await captureDeviceLocation();
        const form = document.getElementById("store-form");
        form.elements.latitude.value = location.latitude;
        form.elements.longitude.value = location.longitude;
        storeLocationCapture = location;
        storeLocationMessage = describeLocation(location);
        status.textContent = storeLocationMessage;
        if (navigator.onLine) reverseGeocodeStorePosition(location.latitude, location.longitude);
    } catch (error) { status.textContent = error.message; showToast(error.message, true); }
    finally { button.disabled = false; }
}

function renderDeliveryTripSelect() {
    const select = document.getElementById("delivery-trip");
    if (!select) return;
    const previous = select.value;
    select.innerHTML = '<option value="">Selecciona una ruta</option>' + state.trips
        .filter(trip => trip.status === "in_progress")
        .map(trip => `<option value="${trip.id}">${escapeHtml(trip.code)}</option>`).join("");
    select.value = previous;
    renderDeliveryStops();
}

function renderDeliveryStops() {
    const trip = state.trips.find(row => row.id === Number(document.getElementById("delivery-trip").value));
    const select = document.getElementById("delivery-stop");
    const previous = select.value;
    select.innerHTML = '<option value="">Selecciona una entrega</option>' + (trip?.stops || [])
        .filter(stop => stop.status === "pending")
        .map(stop => `<option value="${stop.id}">${escapeHtml(stop.store_name || stop.order_code || "Parada")} · ${escapeHtml(statusLabel(stop.status))}</option>`).join("");
    select.value = [...select.options].some(option => option.value === previous) ? previous : "";
    deliveryLocationCapture = null;
    const submit = document.querySelector('#delivery-location-form [type="submit"]');
    if (submit) submit.disabled = true;
}

function initDeliveryLocation() {
    document.getElementById("delivery-trip").addEventListener("change", renderDeliveryStops);
    const button = document.getElementById("btn-delivery-gps");
    const status = document.getElementById("delivery-gps-status");
    const submit = document.querySelector('#delivery-location-form [type="submit"]');
    submit.disabled = true;
    document.getElementById("btn-navigate-next").addEventListener("click", navigateToNextStore);
    document.getElementById("btn-confirm-arrival").addEventListener("click", confirmArrivalDelivery);
    document.getElementById("btn-dismiss-arrival").addEventListener("click", () => {
        const dialog = document.getElementById("arrival-dialog");
        if (dialog.open) dialog.close();
        arrivalDialogStopId = null;
    });
    document.getElementById("delivery-stop").addEventListener("change", () => {
        deliveryLocationCapture = null;
        submit.disabled = true;
        status.textContent = "Captura tu ubicación al llegar a la tienda.";
    });
    button.addEventListener("click", async () => {
        button.disabled = true;
        submit.disabled = true;
        deliveryLocationCapture = null;
        status.textContent = "Permite el acceso a ubicacion. Capturando la posicion real del repartidor...";
        try {
            deliveryLocationCapture = await captureDeviceLocation();
            const trip = state.trips.find(row => row.id === Number(document.getElementById("delivery-trip").value));
            const stop = trip?.stops.find(row => row.id === Number(document.getElementById("delivery-stop").value));
            const arrival = deliveryArrival(deliveryLocationCapture, stop);
            status.textContent = `${describeLocation(deliveryLocationCapture)} ${arrival.message}`;
            submit.disabled = !arrival.allowed;
        } catch (error) { status.textContent = error.message; }
        finally { button.disabled = false; }
    });
    for (const input of document.querySelectorAll('#store-form input[name="latitude"], #store-form input[name="longitude"]')) {
        input.addEventListener("input", () => { storeLocationCapture = null; });
    }
    document.getElementById("delivery-location-form").addEventListener("submit", async event => {
        event.preventDefault();
        const form = event.currentTarget;
        if (!deliveryLocationCapture || Date.now() - Date.parse(deliveryLocationCapture.captured_at) > 300000) {
            status.textContent = "Pulsa Tomar mi ubicacion actual para obtener una lectura reciente antes de guardar."; return;
        }
        const trip = state.trips.find(row => row.id === Number(form.trip_id.value));
        const stop = trip?.stops.find(row => row.id === Number(form.stop_id.value));
        const arrival = deliveryArrival(deliveryLocationCapture, stop);
        if (!arrival.allowed) {
            status.textContent = arrival.message;
            submit.disabled = true;
            return;
        }
        submit.disabled = true;
        const location = deliveryLocationCapture;
        try {
            const response = await postJsonOrQueue(`/api/trips/${form.trip_id.value}/stops/${form.stop_id.value}/`, {
                status: form.status.value, observation: form.observation.value.trim(),
                delivery_latitude: location.latitude, delivery_longitude: location.longitude,
                delivery_accuracy_m: location.accuracy_m, delivery_captured_at: location.captured_at
            }, "Registrar entrega con ubicacion del repartidor");
            deliveryLocationCapture = null;
            status.textContent = response.queued ? "Entrega y ubicacion guardadas en este dispositivo; pendientes de sincronizar." : "Entrega y ubicacion guardadas en el servidor.";
            showToast(status.textContent);
        } catch (error) { status.textContent = error.message; }
        finally { submit.disabled = !deliveryLocationCapture; }
    });
    document.getElementById("offline-pending-list").addEventListener("click", async event => {
        const button = event.target.closest("[data-remove-pending]");
        if (!button || !confirm("Descartar esta operacion elimina este pendiente del dispositivo. Si el servidor ya la recibio, no se deshace. ¿Continuar?")) return;
        try {
            await FlamiaOffline.remove(button.dataset.removePending);
            await refreshOfflineSummary(); await reloadAll();
        } catch (error) { showToast(error.message, true); }
    });
    document.getElementById("btn-export-legacy").addEventListener("click", () => {
        const blob = new Blob([localStorage.getItem(OFFLINE_QUEUE_KEY) || "[]"], { type: "application/json" });
        const link = document.createElement("a");
        link.href = URL.createObjectURL(blob); link.download = "flamia-pendientes-version-anterior.json";
        link.click(); setTimeout(() => URL.revokeObjectURL(link.href), 1000);
    });
    document.querySelector(".logout-form").addEventListener("submit", event => {
        if (!navigator.onLine) {
            event.preventDefault(); showToast("Conectate a internet para cerrar sesion de forma segura.", true);
        } else if (offlinePendingCount && !confirm("Hay operaciones pendientes en este dispositivo. Solo esta cuenta podra sincronizarlas al volver a ingresar. ¿Cerrar sesion?")) event.preventDefault();
    });
}

function distanceMeters(first, second) {
    const radius = 6371000;
    const lat1 = Number(first.latitude) * Math.PI / 180;
    const lat2 = Number(second.latitude) * Math.PI / 180;
    const dLat = lat2 - lat1;
    const dLon = (Number(second.longitude) - Number(first.longitude)) * Math.PI / 180;
    const value = Math.sin(dLat / 2) ** 2
        + Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon / 2) ** 2;
    return 2 * radius * Math.asin(Math.sqrt(value));
}

function deliveryArrival(location, stop) {
    if (!location || !stop || stop.latitude == null || stop.longitude == null) {
        return { allowed: false, distance_m: null, message: "La tienda no tiene una ubicación GPS válida." };
    }
    const distance = distanceMeters(location, { latitude: stop.latitude, longitude: stop.longitude });
    if (location.accuracy_m > MAX_DELIVERY_ACCURACY_METERS) {
        return { allowed: false, distance_m: distance, message: `La precisión GPS es de ${Math.ceil(location.accuracy_m)} m. Espera una lectura de 100 m o mejor.` };
    }
    if (distance > DELIVERY_GEOFENCE_METERS) {
        return { allowed: false, distance_m: distance, message: `Aún estás aproximadamente a ${Math.ceil(distance)} m de la tienda. La entrega se habilita dentro de 120 m.` };
    }
    return { allowed: true, distance_m: distance, message: `Llegada confirmada: estás a ${Math.ceil(distance)} m de la tienda.` };
}

function openArrivalDialog(trip, stop, location, arrival) {
    if (arrivalDialogStopId === stop.id) return;
    arrivalDialogStopId = stop.id;
    deliveryLocationCapture = location;
    const dialog = document.getElementById("arrival-dialog");
    dialog.dataset.tripId = String(trip.id);
    dialog.dataset.stopId = String(stop.id);
    document.getElementById("arrival-title").textContent = `Llegaste a ${stop.store_name || stop.order_code || "la tienda"}`;
    document.getElementById("arrival-message").textContent = `${arrival.message} Precisión aproximada: ${Math.ceil(location.accuracy_m)} m.`;
    document.getElementById("btn-confirm-arrival").style.display = "";
    if (!dialog.open) dialog.showModal();
}

function showSimulatedArrivalDialog() {
    const dialog = document.getElementById("arrival-dialog");
    document.getElementById("arrival-title").textContent = "El vehículo llegó al destino";
    document.getElementById("arrival-message").textContent = "La animación recorrió la carretera calculada. Es una demostración y no registra una entrega real.";
    document.getElementById("btn-confirm-arrival").style.display = "none";
    if (!dialog.open) dialog.showModal();
}

async function confirmArrivalDelivery() {
    const dialog = document.getElementById("arrival-dialog");
    const trip = state.trips.find(row => row.id === Number(dialog.dataset.tripId));
    const stop = trip?.stops.find(row => row.id === Number(dialog.dataset.stopId));
    const location = deliveryLocationCapture;
    const arrival = deliveryArrival(location, stop);
    if (!trip || !stop || !arrival.allowed) {
        showToast(arrival.message || "No se pudo verificar la llegada.", true);
        return;
    }
    const button = document.getElementById("btn-confirm-arrival");
    button.disabled = true;
    try {
        const response = await postJsonOrQueue(`/api/trips/${trip.id}/stops/${stop.id}/`, {
            status: "delivered",
            observation: "Entrega confirmada al ingresar en la geocerca GPS de la tienda.",
            delivery_latitude: location.latitude,
            delivery_longitude: location.longitude,
            delivery_accuracy_m: location.accuracy_m,
            delivery_captured_at: location.captured_at
        }, "Confirmar entrega al llegar a la tienda");
        dialog.close();
        arrivalDialogStopId = null;
        showToast(response.queued ? "Entrega guardada sin conexión." : "Entrega confirmada correctamente.");
    } catch (error) {
        showToast(error.message, true);
    } finally {
        button.disabled = false;
    }
}

async function navigateToNextStore() {
    const trip = state.trips.find(row => row.id === selectedMapTripId)
        || state.trips.find(row => row.status === "in_progress")
        || state.trips.find(row => row.status === "planned");
    if (!trip) {
        showToast("No tienes una ruta activa o seleccionada.", true);
        return;
    }
    const stop = [...(trip.stops || [])]
        .sort((a, b) => a.sequence - b.sequence)
        .find(row => row.status === "pending" && row.latitude != null && row.longitude != null);
    if (!stop) {
        showToast("La ruta no tiene una parada pendiente con ubicacion valida.", true);
        return;
    }
    const navigationWindow = window.open("about:blank", "_blank");
    try {
        showToast("Obteniendo tu ubicacion para abrir la navegacion...");
        const current = await captureDeviceLocation();
        const params = new URLSearchParams({
            api: "1",
            origin: `${current.latitude},${current.longitude}`,
            destination: `${stop.latitude},${stop.longitude}`,
            travelmode: "driving",
        });
        const url = `https://www.google.com/maps/dir/?${params}`;
        if (navigationWindow) navigationWindow.location.href = url;
        else window.location.href = url;
    } catch (error) {
        if (navigationWindow) navigationWindow.close();
        showToast(error.message, true);
    }
}
