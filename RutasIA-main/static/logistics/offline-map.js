/* Offline map for the driver: the saved road shape, the stops and the phone's GPS, drawn with
   Leaflet stored inside the app. It only opens when Google Maps is unavailable (no signal);
   with internet the Google map and navigation work exactly as before. */
const OFFLINE_ROUTES_KEY = `flamia.offlineRoutes.${document.body.dataset.userId || "anon"}`;
const OFFLINE_ROUTES_KEEP = 10;
const OFFLINE_ROUTE_MAX_POINTS = 1500;
const OFFLINE_VIEW_HTML = `
<div class="offline-map-view" id="offline-map-view" hidden>
    <div id="offline-map"></div>
    <div class="nav-banner" id="offline-map-banner" aria-live="polite">
        <div class="nav-icon" id="offline-map-icon"></div>
        <div class="nav-text">
            <div class="nav-distance" id="offline-map-distance">Buscando GPS...</div>
            <div class="nav-instruction" id="offline-map-target"></div>
            <div class="nav-current" id="offline-map-note"></div>
        </div>
        <button type="button" class="nav-banner-action" id="offline-map-deliver" hidden>Registrar entrega</button>
    </div>
    <div class="nav-footer">
        <div class="nav-eta">
            <strong id="offline-map-progress"></strong>
            <span id="offline-map-source"></span>
        </div>
        <div class="nav-actions">
            <button type="button" class="btn-small btn-neutral" id="offline-map-center">Centrar</button>
            <button type="button" class="btn-small btn-danger" id="offline-map-exit">Salir</button>
        </div>
    </div>
</div>`;

let offlineView = null;

function offlinePoint(value) {
    return typeof value.lat === "function" ? { lat: value.lat(), lng: value.lng() } : { lat: Number(value.lat), lng: Number(value.lng) };
}

function googleMapsReady() {
    return navigator.onLine && Boolean(window.google?.maps);
}

// ── Rutas guardadas ──

function readOfflineRoutes() {
    try { return JSON.parse(localStorage.getItem(OFFLINE_ROUTES_KEY)) || {}; } catch (_) { return {}; }
}

// Called whenever Google calculates a road route online, so the same shape is available offline.
function saveOfflineRoute(tripId, path) {
    if (!tripId || !path?.length) return;
    const stride = Math.max(1, Math.ceil(path.length / OFFLINE_ROUTE_MAX_POINTS));
    const points = path
        .filter((_, index) => index % stride === 0 || index === path.length - 1)
        .map(offlinePoint)
        .map(({ lat, lng }) => [Number(lat.toFixed(6)), Number(lng.toFixed(6))]);
    const routes = readOfflineRoutes();
    routes[tripId] = { points, saved_at: new Date().toISOString() };
    const recent = Object.entries(routes)
        .sort((a, b) => b[1].saved_at.localeCompare(a[1].saved_at))
        .slice(0, OFFLINE_ROUTES_KEEP);
    try { localStorage.setItem(OFFLINE_ROUTES_KEY, JSON.stringify(Object.fromEntries(recent))); }
    catch (_) { /* Without storage the offline map falls back to straight lines. */ }
}

// ── Vista ──

function offlineTripStops(trip) {
    return [...(trip.stops || [])]
        .filter((stop) => stop.latitude != null && stop.longitude != null)
        .sort((a, b) => a.sequence - b.sequence);
}

function offlineCardinal(bearing) {
    return ["norte", "noreste", "este", "sureste", "sur", "suroeste", "oeste", "noroeste"][Math.round(bearing / 45) % 8];
}

function offlineArrowIcon(angle) {
    return `<svg viewBox="0 0 24 24" aria-hidden="true"><g transform="rotate(${angle} 12 12)"><path d="M12 21V4M6 10l6-6 6 6"/></g></svg>`;
}

function openOfflineMap(trip = navActiveTrip()) {
    if (!trip) {
        showToast("No tienes una ruta asignada o seleccionada.", true);
        return;
    }
    if (!window.L) {
        showToast("El mapa sin conexion no esta disponible. Abre Flamia con internet una vez para descargarlo.", true);
        return;
    }
    const stops = offlineTripStops(trip);
    if (!stops.length) {
        showToast("La ruta no tiene paradas con ubicacion.", true);
        return;
    }
    closeOfflineMap();
    document.getElementById("offline-map-view").hidden = false;
    document.body.classList.add("is-offline-map");

    const leafletMap = L.map("offline-map", { attributionControl: navigator.onLine });
    // Street tiles only load with signal; offline the route is drawn over a plain grid.
    if (navigator.onLine) {
        L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
            maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
        }).addTo(leafletMap);
    }
    const saved = readOfflineRoutes()[trip.id];
    const base = state.departments.find((department) => department.name === trip.origin_name);
    const straight = [
        ...(base?.latitude ? [[Number(base.latitude), Number(base.longitude)]] : []),
        ...stops.map((stop) => [Number(stop.latitude), Number(stop.longitude)])
    ];
    const shape = saved?.points?.length ? saved.points : straight;
    L.polyline(shape, { color: "#0b3a8a", weight: 10, opacity: 1, interactive: false }).addTo(leafletMap);
    L.polyline(shape, { color: "#38bdf8", weight: 5, opacity: 1, interactive: false, dashArray: saved ? null : "10 10" }).addTo(leafletMap);
    leafletMap.fitBounds(L.latLngBounds([...shape, ...straight]), { padding: [60, 60] });

    offlineView = { tripId: trip.id, map: leafletMap, following: true, position: null, heading: null, stopsKey: "", stopMarkers: [] };
    leafletMap.on("dragstart", () => { if (offlineView) offlineView.following = false; });
    document.getElementById("offline-map-source").textContent = saved
        ? `Ruta guardada el ${new Date(saved.saved_at).toLocaleString("es-GT", { dateStyle: "short", timeStyle: "short" })}`
        : "Sin ruta guardada: lineas rectas en el orden de visita";
    offlineRender();

    if (navigator.geolocation) {
        offlineView.watchId = navigator.geolocation.watchPosition(onOfflinePosition, (error) => {
            if (offlineView) document.getElementById("offline-map-note").textContent = `Sin señal GPS: ${error.message}`;
        }, { enableHighAccuracy: true, maximumAge: 2000, timeout: 20000 });
    }
    offlineKeepScreenOn();
}

function closeOfflineMap() {
    if (!offlineView) return;
    if (offlineView.watchId !== undefined) navigator.geolocation.clearWatch(offlineView.watchId);
    offlineView.wakeLock?.release().catch(() => {});
    offlineView.map.remove();
    offlineView = null;
    document.getElementById("offline-map-view").hidden = true;
    document.body.classList.remove("is-offline-map");
}

function onOfflinePosition(position) {
    if (!offlineView) return;
    const { latitude, longitude, accuracy, heading } = position.coords;
    const point = { lat: latitude, lng: longitude };
    const previous = offlineView.position;
    if (Number.isFinite(heading)) offlineView.heading = heading;
    else if (previous && navDistance(previous, point) > 3) offlineView.heading = navBearing(previous, point);
    offlineView.position = point;
    offlineView.accuracy = accuracy;

    if (!offlineView.driverMarker) {
        offlineView.accuracyCircle = L.circle(point, { radius: accuracy || 0, stroke: false, fillColor: "#38bdf8", fillOpacity: 0.15, interactive: false }).addTo(offlineView.map);
        offlineView.driverMarker = L.marker(point, {
            zIndexOffset: 500, interactive: false,
            icon: L.divIcon({
                className: "offline-driver",
                html: '<div class="offline-driver-arrow"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2 20 21 12 16 4 21Z"/></svg></div>',
                iconSize: [34, 34]
            })
        }).addTo(offlineView.map);
        // First fix: frame the driver together with the next stop so the route is in view.
        const next = offlineNextStop();
        const focus = next ? [point, { lat: Number(next.latitude), lng: Number(next.longitude) }] : [point];
        offlineView.map.fitBounds(L.latLngBounds(focus), { paddingTopLeft: [40, 150], paddingBottomRight: [40, 160], maxZoom: 16 });
    } else {
        offlineView.driverMarker.setLatLng(point);
        offlineView.accuracyCircle.setLatLng(point).setRadius(accuracy || 0);
        if (offlineView.following) offlineView.map.panTo(point);
    }
    // Leaflet positions the marker element with a transform, so the arrow inside it is what rotates.
    const arrow = offlineView.driverMarker.getElement()?.querySelector(".offline-driver-arrow");
    if (arrow) arrow.style.transform = `rotate(${offlineView.heading || 0}deg)`;
    offlineRender();
}

function offlineDrawStops(stops) {
    // Delivered stops change while offline (queued deliveries), so markers follow the projected state.
    const key = stops.map((stop) => `${stop.id}:${stop.status}`).join(",");
    if (key === offlineView.stopsKey) return;
    offlineView.stopsKey = key;
    offlineView.stopMarkers.forEach((marker) => marker.remove());
    offlineView.stopMarkers = stops.map((stop, index) => {
        const done = stop.status !== "pending";
        return L.marker([Number(stop.latitude), Number(stop.longitude)], {
            title: stop.store_name || stop.order_code || "",
            zIndexOffset: 400,
            icon: L.divIcon({ className: `offline-stop-pin${done ? " is-done" : ""}`, html: done ? "✓" : String(index + 1), iconSize: [28, 28] })
        }).addTo(offlineView.map);
    });
}

function offlineNextStop() {
    const trip = state.trips.find((row) => row.id === offlineView.tripId);
    return trip ? offlineTripStops(trip).find((stop) => stop.status === "pending") : null;
}

function offlineRender() {
    const trip = state.trips.find((row) => row.id === offlineView.tripId);
    if (!trip) return;
    const stops = offlineTripStops(trip);
    offlineDrawStops(stops);
    const pending = stops.filter((stop) => stop.status === "pending");
    const banner = document.getElementById("offline-map-banner");
    const deliver = document.getElementById("offline-map-deliver");
    const set = (id, text) => { document.getElementById(id).textContent = text; };
    document.getElementById("offline-map-progress").textContent = pending.length
        ? `Parada ${stops.length - pending.length + 1} de ${stops.length}`
        : "Todas las paradas visitadas";
    banner.classList.remove("is-arrived");
    deliver.hidden = true;

    const next = pending[0];
    if (!next) {
        document.getElementById("offline-map-icon").innerHTML = navManeuverIcon("arrive");
        set("offline-map-distance", "Ruta completada");
        set("offline-map-target", "No quedan paradas pendientes.");
        set("offline-map-note", "Las entregas se enviaran al recuperar la señal.");
        return;
    }
    const name = next.store_name || next.order_code || `Parada ${next.sequence}`;
    if (!offlineView.position) {
        document.getElementById("offline-map-icon").innerHTML = offlineArrowIcon(0);
        set("offline-map-distance", "Buscando GPS...");
        set("offline-map-target", `Siguiente: ${name}`);
        set("offline-map-note", "Activa la ubicacion del celular. El GPS funciona sin internet.");
        return;
    }
    const target = { lat: Number(next.latitude), lng: Number(next.longitude) };
    const bearing = navBearing(offlineView.position, target);
    document.getElementById("offline-map-icon").innerHTML = offlineArrowIcon(bearing);
    set("offline-map-distance", navFormatDistance(navDistance(offlineView.position, target)));
    set("offline-map-target", `${name} · al ${offlineCardinal(bearing)}`);
    set("offline-map-note", "Distancia en linea recta. Sigue la linea azul del mapa.");

    if (state.currentUser?.role !== "driver") return;
    const location = {
        latitude: offlineView.position.lat,
        longitude: offlineView.position.lng,
        accuracy_m: Number.isFinite(offlineView.accuracy) ? offlineView.accuracy : 999,
        captured_at: new Date().toISOString()
    };
    const arrival = deliveryArrival(location, next);
    if (!arrival.allowed) return;
    offlineView.arrival = { trip, stop: next, location, arrival };
    banner.classList.add("is-arrived");
    set("offline-map-distance", "Llegaste");
    set("offline-map-note", arrival.message);
    deliver.hidden = false;
}

async function offlineKeepScreenOn() {
    try { if (offlineView && "wakeLock" in navigator) offlineView.wakeLock = await navigator.wakeLock.request("screen"); }
    catch (_) { /* The screen may still turn off; the map keeps working when reopened. */ }
}

function updateOfflineMapButtons() {
    const unavailable = !googleMapsReady();
    const mapButton = document.getElementById("btn-offline-map");
    if (mapButton) mapButton.hidden = !unavailable;
    const navButton = document.getElementById("nav-offline-map");
    if (navButton) navButton.hidden = !unavailable;
}

document.addEventListener("DOMContentLoaded", () => {
    document.body.insertAdjacentHTML("beforeend", OFFLINE_VIEW_HTML);
    const controls = document.querySelector("#tab-map .gps-sim-controls");
    const mapButton = '<button type="button" id="btn-offline-map" class="btn-small btn-neutral" hidden>Mapa sin conexion</button>';
    const startNav = document.getElementById("btn-start-nav");
    if (startNav) startNav.insertAdjacentHTML("afterend", mapButton);
    else controls?.insertAdjacentHTML("afterbegin", mapButton);
    // During Google navigation, offer the offline map if the signal drops.
    document.querySelector("#nav-overlay .nav-actions")?.insertAdjacentHTML("afterbegin",
        '<button type="button" class="btn-small btn-neutral" id="nav-offline-map" hidden>Mapa sin conexion</button>');

    document.getElementById("btn-offline-map")?.addEventListener("click", () => openOfflineMap());
    document.getElementById("nav-offline-map")?.addEventListener("click", () => {
        const trip = nav?.trip;
        stopNavigation();
        openOfflineMap(trip || navActiveTrip());
    });
    // Without Google Maps, "Navegar ruta" opens the offline map instead of showing an error.
    document.addEventListener("click", (event) => {
        if (!event.target.closest("#btn-start-nav") || googleMapsReady()) return;
        event.preventDefault();
        event.stopPropagation();
        openOfflineMap();
    }, true);
    document.getElementById("offline-map-exit").addEventListener("click", closeOfflineMap);
    document.getElementById("offline-map-center").addEventListener("click", () => {
        if (!offlineView?.position) return;
        offlineView.following = true;
        offlineView.map.setView(offlineView.position, 16);
    });
    document.getElementById("offline-map-deliver").addEventListener("click", () => {
        const pending = offlineView?.arrival;
        if (pending) openArrivalDialog(pending.trip, pending.stop, pending.location, pending.arrival);
    });
    document.getElementById("arrival-dialog")?.addEventListener("close", () => { if (offlineView) offlineRender(); });
    window.addEventListener("online", updateOfflineMapButtons);
    window.addEventListener("offline", updateOfflineMapButtons);
    document.addEventListener("visibilitychange", () => { if (!document.hidden && offlineView) offlineKeepScreenOn(); });
    updateOfflineMapButtons();
});
