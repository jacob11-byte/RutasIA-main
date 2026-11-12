/* Turn-by-turn driving mode: full-screen map, next maneuver and live GPS.
   Independent of the trip map rendering; it requests its own route from the driver's position. */
const NAV_EARTH_M = 6371000;
const NAV_OFF_ROUTE_M = 60;
const NAV_ARRIVAL_M = 40;
const NAV_LOOKAHEAD_STEPS = 6;
const NAV_OVERLAY_HTML = `
<div class="nav-overlay" id="nav-overlay">
    <div class="nav-banner" id="nav-banner" aria-live="polite">
        <div class="nav-icon" id="nav-icon"></div>
        <div class="nav-text">
            <div class="nav-distance" id="nav-distance">—</div>
            <div class="nav-instruction" id="nav-instruction">Calculando ruta...</div>
            <div class="nav-current" id="nav-current"></div>
        </div>
        <button type="button" class="nav-banner-action" id="nav-banner-action" hidden></button>
    </div>
    <button type="button" class="nav-recenter" id="nav-recenter" hidden>Recentrar</button>
    <div class="nav-footer">
        <div class="nav-eta">
            <strong id="nav-eta-time">—</strong>
            <span id="nav-eta-detail"></span>
        </div>
        <div class="nav-next-stop" id="nav-next-stop"></div>
        <div class="nav-actions">
            <button type="button" class="btn-small btn-neutral" id="nav-voice">Voz: sí</button>
            <button type="button" class="btn-small btn-neutral" id="nav-simulate" hidden>Simular</button>
            <button type="button" class="btn-small btn-danger" id="nav-exit">Salir</button>
        </div>
    </div>
</div>`;

let nav = null;

// ── Geometria ──

function navPoint(value) {
    return typeof value.lat === "function" ? { lat: value.lat(), lng: value.lng() } : { lat: Number(value.lat), lng: Number(value.lng) };
}

function navDistance(a, b) {
    const rad = Math.PI / 180;
    const dLat = (b.lat - a.lat) * rad;
    const dLng = (b.lng - a.lng) * rad;
    const h = Math.sin(dLat / 2) ** 2 + Math.cos(a.lat * rad) * Math.cos(b.lat * rad) * Math.sin(dLng / 2) ** 2;
    return 2 * NAV_EARTH_M * Math.asin(Math.sqrt(h));
}

function navBearing(a, b) {
    const rad = Math.PI / 180;
    const y = Math.sin((b.lng - a.lng) * rad) * Math.cos(b.lat * rad);
    const x = Math.cos(a.lat * rad) * Math.sin(b.lat * rad) - Math.sin(a.lat * rad) * Math.cos(b.lat * rad) * Math.cos((b.lng - a.lng) * rad);
    return (Math.atan2(y, x) / rad + 360) % 360;
}

// Equirectangular projection is accurate enough at street-segment scale.
function navSegmentDistance(p, a, b) {
    const rad = Math.PI / 180;
    const kx = Math.cos(p.lat * rad) * NAV_EARTH_M * rad;
    const ky = NAV_EARTH_M * rad;
    const ax = (a.lng - p.lng) * kx, ay = (a.lat - p.lat) * ky;
    const dx = (b.lng - a.lng) * kx, dy = (b.lat - a.lat) * ky;
    const length = dx * dx + dy * dy;
    const t = length ? Math.max(0, Math.min(1, -(ax * dx + ay * dy) / length)) : 0;
    return { distance: Math.hypot(ax + t * dx, ay + t * dy), t };
}

// Distance from the point to the path, and distance left along the path to its end.
function navMatchPath(point, path) {
    if (path.length < 2) return { distance: navDistance(point, path[0]), remaining: 0 };
    let best = { distance: Infinity, segment: 0, t: 0 };
    for (let i = 0; i < path.length - 1; i++) {
        const { distance, t } = navSegmentDistance(point, path[i], path[i + 1]);
        if (distance < best.distance) best = { distance, segment: i, t };
    }
    let remaining = navDistance(path[best.segment], path[best.segment + 1]) * (1 - best.t);
    for (let i = best.segment + 1; i < path.length - 1; i++) remaining += navDistance(path[i], path[i + 1]);
    return { distance: best.distance, remaining };
}

// Only looks ahead (never back) so a parallel street already driven is not chosen.
// Ties go to the later step: at a junction the driver is starting the next maneuver.
function navLocate(steps, fromIndex, point) {
    let best = null;
    const last = Math.min(steps.length, fromIndex + NAV_LOOKAHEAD_STEPS);
    for (let index = fromIndex; index < last; index++) {
        const match = navMatchPath(point, steps[index].path);
        if (!best || match.distance <= best.distance + 1) best = { index, ...match };
    }
    return { ...best, offRoute: best.distance > NAV_OFF_ROUTE_M };
}

// ── Texto ──

function navInstructionText(html) {
    const doc = new DOMParser().parseFromString(html || "", "text/html");
    const details = [...doc.body.querySelectorAll("div")].map((div) => {
        const text = div.textContent.trim();
        div.remove();
        return text;
    }).filter(Boolean);
    return { main: doc.body.textContent.replace(/\s+/g, " ").trim(), detail: details.join(" · ") };
}

function navFormatDistance(meters) {
    if (meters >= 1000) return `${(meters / 1000).toFixed(1)} km`;
    return `${Math.max(10, Math.round(meters / 10) * 10)} m`;
}

function navFormatDuration(seconds) {
    const minutes = Math.max(1, Math.round(seconds / 60));
    return minutes < 60 ? `${minutes} min` : `${Math.floor(minutes / 60)} h ${minutes % 60} min`;
}

function navManeuverIcon(maneuver = "") {
    const svg = (body) => `<svg viewBox="0 0 24 24" aria-hidden="true">${body}</svg>`;
    if (maneuver === "arrive") return svg('<path d="M6 21V4h11l-2.5 4.5L17 13H6"/>');
    if (maneuver.startsWith("roundabout")) return svg('<circle cx="12" cy="10" r="4"/><path d="M12 14v7M16 6l1.5-2.5M16 6l-2.8.3"/>');
    if (maneuver.startsWith("uturn")) {
        const mirror = maneuver.endsWith("right") ? ' transform="scale(-1 1) translate(-24 0)"' : "";
        return svg(`<g${mirror}><path d="M16 21V10a5 5 0 0 0-10 0v4"/><path d="m3 11 3 3 3-3"/></g>`);
    }
    const angles = {
        "turn-sharp-left": -135, "turn-left": -90, "turn-slight-left": -45, "keep-left": -30, "ramp-left": -30, "fork-left": -30,
        "turn-sharp-right": 135, "turn-right": 90, "turn-slight-right": 45, "keep-right": 30, "ramp-right": 30, "fork-right": 30
    };
    return svg(`<g transform="rotate(${angles[maneuver] || 0} 12 12)"><path d="M12 21V4M6 10l6-6 6 6"/></g>`);
}

function navSpeak(text) {
    if (!nav?.voice || !("speechSynthesis" in window) || !text) return;
    try {
        speechSynthesis.cancel();
        const utterance = new SpeechSynthesisUtterance(text);
        utterance.lang = "es-MX";
        const voice = speechSynthesis.getVoices().find((item) => item.lang.toLowerCase().startsWith("es"));
        if (voice) utterance.voice = voice;
        speechSynthesis.speak(utterance);
    } catch (_) {
        // Voice is optional; the banner remains the source of truth.
    }
}

// ── Ruta ──

function navActiveTrip() {
    return state.trips.find((trip) => trip.id === selectedMapTripId)
        || state.trips.find((trip) => trip.status === "in_progress")
        || state.trips.find((trip) => trip.status === "planned");
}

function navCurrentPosition() {
    return new Promise((resolve) => {
        if (!window.isSecureContext || !navigator.geolocation) { resolve(null); return; }
        navigator.geolocation.getCurrentPosition(
            (position) => resolve({
                lat: position.coords.latitude,
                lng: position.coords.longitude,
                accuracy: position.coords.accuracy
            }),
            () => resolve(null),
            { enableHighAccuracy: true, timeout: 8000, maximumAge: 15000 }
        );
    });
}

// Both Google services are normalized to the same step shape; steps without geometry are dropped.
function navNormalizeLegs(legs) {
    return legs.flatMap((steps, legIndex) => {
        const usable = steps.filter((step) => step.path.length);
        return usable.map((step, index) => ({ ...step, legIndex, isLegEnd: index === usable.length - 1 }));
    });
}

function navStepsFromRoutes(route) {
    return navNormalizeLegs(route.legs.map((leg) => leg.steps.map((step) => ({
        // Routes API uses TURN_LEFT style names; Directions uses turn-left.
        maneuver: String(step.navigationInstruction?.maneuver || "").toLowerCase().replaceAll("_", "-"),
        text: navInstructionText(step.navigationInstruction?.instructions || ""),
        distance: step.distanceMeters || 0,
        duration: (step.staticDurationMillis || 0) / 1000,
        path: (step.path || []).map(navPoint)
    }))));
}

function navStepsFromDirections(result) {
    return navNormalizeLegs(result.routes[0].legs.map((leg) => leg.steps.map((step) => ({
        maneuver: step.maneuver || "",
        text: navInstructionText(step.instructions),
        distance: step.distance?.value || 0,
        duration: step.duration?.value || 0,
        path: (step.path?.length ? step.path : [step.start_location, step.end_location]).map(navPoint)
    }))));
}

function navDirections(origin, points) {
    return new Promise((resolve, reject) => {
        new google.maps.DirectionsService().route({
            origin,
            destination: points[points.length - 1],
            waypoints: points.slice(0, -1).map((location) => ({ location, stopover: true })),
            travelMode: google.maps.TravelMode.DRIVING
        }, (result, status) => (status === "OK" ? resolve(result) : reject(new Error(`Directions: ${status}`))));
    });
}

// Routes API is Google's current service; Directions (legacy) only works on keys that still have it.
async function navRequestRoute(origin, stops) {
    const points = stops.map((stop) => ({ lat: Number(stop.latitude), lng: Number(stop.longitude) }));
    const errors = [];
    try {
        const { Route } = await google.maps.importLibrary("routes");
        const { routes } = await Route.computeRoutes({
            origin, destination: points[points.length - 1], intermediates: points.slice(0, -1),
            travelMode: "DRIVING", language: "es", region: "gt", fields: ["legs"]
        });
        const steps = routes?.length ? navStepsFromRoutes(routes[0]) : [];
        if (steps.length) return steps;
        errors.push("Routes: sin resultados");
    } catch (error) {
        errors.push(`Routes: ${error.message || error}`);
    }
    try {
        const steps = navStepsFromDirections(await navDirections(origin, points));
        if (steps.length) return steps;
        errors.push("Directions: sin resultados");
    } catch (error) {
        errors.push(error.message);
    }
    console.warn("Navegacion sin ruta de Google:", errors.join(" | "));
    throw new Error("Google no entrego la ruta de manejo. Habilita Routes API para la clave de Google Maps.");
}

function navStopName(legIndex) {
    const stop = nav.stops[legIndex];
    return stop ? (stop.store_name || stop.order_code || `Parada ${stop.sequence}`) : "Destino";
}

async function navLoadRoute(origin, stops) {
    const steps = await navRequestRoute(origin, stops);
    if (!nav) return;
    nav.stops = stops;
    nav.steps = steps;
    if (typeof saveOfflineRoute === "function") saveOfflineRoute(nav.trip.id, steps.flatMap((step) => step.path));
    nav.stepIndex = 0;
    nav.arrivals = new Set();
    nav.arrivedLeg = null;
    nav.announcedStep = -1;
    nav.offRouteCount = 0;
    const path = steps.flatMap((step) => step.path);
    nav.lines.forEach((line) => line.setMap(null));
    nav.lines = [
        new google.maps.Polyline({ map, path, strokeColor: "#0b3a8a", strokeOpacity: 1, strokeWeight: 11, zIndex: 30, clickable: false }),
        new google.maps.Polyline({ map, path, strokeColor: "#38bdf8", strokeOpacity: 1, strokeWeight: 6, zIndex: 31, clickable: false })
    ];
    nav.stopMarkers.forEach((marker) => marker.setMap(null));
    nav.stopMarkers = stops.map((stop, index) => new google.maps.Marker({
        position: { lat: Number(stop.latitude), lng: Number(stop.longitude) },
        map,
        label: { text: String(index + 1), color: "#ffffff", fontWeight: "700" },
        title: stop.store_name || stop.order_code || "",
        zIndex: 40
    }));
}

// ── Modo navegacion ──

async function startNavigation() {
    if (!window.google?.maps || !map) {
        showToast("El mapa necesita conexion para calcular la ruta de manejo.", true);
        return;
    }
    const trip = navActiveTrip();
    if (!trip) {
        showToast("Selecciona una ruta en el mapa o inicia una ruta asignada.", true);
        return;
    }
    const stops = [...(trip.stops || [])]
        .filter((stop) => stop.status === "pending" && stop.latitude != null && stop.longitude != null)
        .sort((a, b) => a.sequence - b.sequence)
        .slice(0, 26);
    if (!stops.length) {
        showToast("La ruta no tiene paradas pendientes con ubicacion.", true);
        return;
    }
    const button = document.getElementById("btn-start-nav");
    button.disabled = true;
    showToast("Calculando la ruta desde tu ubicacion...");
    try {
        const here = await navCurrentPosition();
        const base = state.departments.find((department) => department.name === trip.origin_name);
        const origin = here || (base?.latitude ? { lat: Number(base.latitude), lng: Number(base.longitude) } : null);
        if (!origin) throw new Error("No se obtuvo tu ubicacion ni la base de la ruta.");
        nav = {
            trip, stops, steps: [], stepIndex: 0, following: true, position: null, simTimer: null,
            voice: navVoicePreference(), stopMarkers: [], lines: [], arrivals: new Set(), announcedStep: -1, nearAnnounced: false,
            driverMarker: new google.maps.Marker({ map, zIndex: 50, icon: navDriverIcon(0) }),
            accuracyCircle: new google.maps.Circle({ map, strokeOpacity: 0, fillColor: "#38bdf8", fillOpacity: 0.15, clickable: false })
        };
        await navLoadRoute(origin, stops);
        navEnterUi();
        if (here) onNavPosition(here, null, here.accuracy);
        else {
            map.panTo(origin);
            navRender(null);
        }
        nav.watchId = navigator.geolocation?.watchPosition(
            (position) => {
                if (nav?.simTimer) return;
                const { latitude, longitude, heading, accuracy } = position.coords;
                onNavPosition({ lat: latitude, lng: longitude }, heading, accuracy);
            },
            (error) => { if (nav) document.getElementById("nav-current").textContent = `Sin señal GPS: ${error.message}`; },
            { enableHighAccuracy: true, maximumAge: 2000, timeout: 20000 }
        );
    } catch (error) {
        stopNavigation();
        showToast(error.message, true);
    } finally {
        button.disabled = false;
    }
}

function navEnterUi() {
    document.body.classList.add("is-navigating");
    document.querySelector("#tab-map .map-card").classList.add("is-navigating");
    map.setOptions({ disableDefaultUI: true, gestureHandling: "greedy" });
    map.setZoom(17);
    nav.dragListener = map.addListener("dragstart", () => {
        if (!nav) return;
        nav.following = false;
        document.getElementById("nav-recenter").hidden = false;
    });
    document.getElementById("nav-voice").textContent = nav.voice ? "Voz: sí" : "Voz: no";
    document.getElementById("nav-simulate").hidden = !["admin", "supervisor"].includes(state.currentUser?.role);
    navKeepScreenOn();
}

function stopNavigation() {
    if (!nav) return;
    if (nav.watchId !== undefined) navigator.geolocation.clearWatch(nav.watchId);
    clearInterval(nav.simTimer);
    if (nav.dragListener) google.maps.event.removeListener(nav.dragListener);
    nav.lines.forEach((line) => line.setMap(null));
    nav.driverMarker.setMap(null);
    nav.accuracyCircle.setMap(null);
    nav.stopMarkers.forEach((marker) => marker.setMap(null));
    nav.wakeLock?.release().catch(() => {});
    if ("speechSynthesis" in window) speechSynthesis.cancel();
    nav = null;
    document.body.classList.remove("is-navigating");
    document.querySelector("#tab-map .map-card")?.classList.remove("is-navigating");
    document.getElementById("nav-recenter").hidden = true;
    document.getElementById("nav-banner-action").hidden = true;
    map?.setOptions({ disableDefaultUI: false, gestureHandling: "auto" });
}

function navDriverIcon(heading) {
    return {
        path: google.maps.SymbolPath.FORWARD_CLOSED_ARROW,
        scale: 7, rotation: heading || 0,
        fillColor: "#1d6fd8", fillOpacity: 1, strokeColor: "#ffffff", strokeWeight: 2
    };
}

function onNavPosition(point, heading, accuracy) {
    if (!nav?.steps.length) return;
    const previous = nav.position;
    if (heading == null && previous && navDistance(previous, point) > 3) heading = navBearing(previous, point);
    nav.position = point;
    nav.accuracy = accuracy;
    if (heading != null) nav.heading = heading;
    nav.driverMarker.setPosition(point);
    nav.driverMarker.setIcon(navDriverIcon(nav.heading));
    nav.accuracyCircle.setCenter(point);
    nav.accuracyCircle.setRadius(accuracy || 0);
    if (nav.following) map.panTo(point);

    const match = navLocate(nav.steps, nav.stepIndex, point);
    nav.offRouteCount = match.offRoute ? nav.offRouteCount + 1 : 0;
    if (!match.offRoute) nav.stepIndex = match.index;
    nav.steps.forEach((step, index) => {
        if (!step.isLegEnd || index > nav.stepIndex || nav.arrivals.has(step.legIndex)) return;
        const near = navDistance(point, step.path[step.path.length - 1]) <= NAV_ARRIVAL_M;
        // A stop left behind counts as passed; only a close fix announces the arrival.
        if (!near && index === nav.stepIndex) return;
        nav.arrivals.add(step.legIndex);
        if (!near) return;
        nav.arrivedLeg = step.legIndex;
        const done = step.legIndex === nav.stops.length - 1;
        navSpeak(`Llegaste a ${navStopName(step.legIndex)}.${done ? " Ruta completada." : ""}`);
        const arrivedStop = nav.stops[step.legIndex];
        if (state.currentUser?.role === "driver" && arrivedStop) {
            const location = {
                latitude: point.lat,
                longitude: point.lng,
                accuracy_m: Number.isFinite(accuracy) ? accuracy : 999,
                captured_at: new Date().toISOString()
            };
            const arrival = deliveryArrival(location, arrivedStop);
            if (arrival.allowed) openArrivalDialog(nav.trip, arrivedStop, location, arrival);
        } else if (arrivedStop) {
            showSimulatedArrivalDialog();
        }
    });
    navRender(match);
}

function navRender(match) {
    const step = nav.steps[nav.stepIndex];
    const remainingInStep = match ? match.remaining : step.distance;
    const banner = document.getElementById("nav-banner");
    const action = document.getElementById("nav-banner-action");
    const arrivedStop = nav.arrivedLeg != null ? nav.stops[nav.arrivedLeg] : null;
    const atStop = arrivedStop && nav.position
        && navDistance(nav.position, { lat: Number(arrivedStop.latitude), lng: Number(arrivedStop.longitude) }) <= NAV_ARRIVAL_M * 2;
    const offRoute = nav.offRouteCount >= 3;

    banner.classList.toggle("is-off-route", offRoute);
    banner.classList.toggle("is-arrived", Boolean(atStop) && !offRoute);
    action.hidden = !(offRoute || atStop);

    let icon, distance, instruction, current;
    if (offRoute) {
        icon = navManeuverIcon("uturn-left");
        distance = "Fuera de ruta";
        instruction = "Regresa a la ruta marcada o recalcula desde tu ubicacion.";
        current = "";
        action.textContent = "Recalcular";
        action.dataset.action = "recalculate";
    } else if (atStop) {
        const last = nav.arrivedLeg === nav.stops.length - 1;
        icon = navManeuverIcon("arrive");
        distance = last ? "Ruta completada" : "Llegaste";
        instruction = navStopName(nav.arrivedLeg);
        current = last ? "Registra la entrega de la ultima parada." : `Siguiente: ${navStopName(nav.arrivedLeg + 1)}`;
        action.textContent = "Registrar entrega";
        action.dataset.action = "deliver";
    } else {
        const next = step.isLegEnd ? null : nav.steps[nav.stepIndex + 1];
        icon = navManeuverIcon(next ? next.maneuver : "arrive");
        distance = navFormatDistance(remainingInStep);
        instruction = next ? next.text.main : `Llegada a ${navStopName(step.legIndex)}`;
        current = [step.text.main, step.text.detail].filter(Boolean).join(" · ");
        navAnnounce(remainingInStep, instruction);
    }
    document.getElementById("nav-icon").innerHTML = icon;
    document.getElementById("nav-distance").textContent = distance;
    document.getElementById("nav-instruction").textContent = instruction;
    document.getElementById("nav-current").textContent = current;

    const rest = nav.steps.slice(nav.stepIndex + 1);
    const ratio = step.distance ? remainingInStep / step.distance : 0;
    const meters = remainingInStep + rest.reduce((sum, item) => sum + item.distance, 0);
    const seconds = step.duration * ratio + rest.reduce((sum, item) => sum + item.duration, 0);
    const arrival = new Date(Date.now() + seconds * 1000).toLocaleTimeString("es-GT", { hour: "2-digit", minute: "2-digit" });
    document.getElementById("nav-eta-time").textContent = `${navFormatDuration(seconds)} · ${arrival}`;
    document.getElementById("nav-eta-detail").textContent = `${navFormatDistance(meters)} restantes`;
    const pending = nav.stops.length - nav.arrivals.size;
    document.getElementById("nav-next-stop").textContent = pending
        ? `Parada ${nav.stops.length - pending + 1} de ${nav.stops.length}: ${navStopName(step.legIndex)}`
        : "Todas las paradas visitadas";
}

function navAnnounce(remaining, instruction) {
    if (nav.announcedStep !== nav.stepIndex) {
        nav.announcedStep = nav.stepIndex;
        nav.nearAnnounced = remaining <= 60;
        navSpeak(remaining > 60 ? `En ${navFormatDistance(remaining)}, ${instruction}` : instruction);
    } else if (!nav.nearAnnounced && remaining <= 60) {
        nav.nearAnnounced = true;
        navSpeak(instruction);
    }
}

async function navRecalculate() {
    if (!nav?.position) return;
    const remaining = nav.stops.filter((_, index) => !nav.arrivals.has(index));
    if (!remaining.length) return;
    try {
        await navLoadRoute(nav.position, remaining);
        onNavPosition(nav.position, nav.heading, null);
        showToast("Ruta recalculada desde tu ubicacion.");
    } catch (error) {
        showToast(error.message, true);
    }
}

function navOpenDelivery() {
    const trip = nav.trip;
    const stop = nav.stops[nav.arrivedLeg];
    if (state.currentUser?.role === "driver" && stop && nav.position) {
        const location = {
            latitude: nav.position.lat,
            longitude: nav.position.lng,
            accuracy_m: Number.isFinite(nav.accuracy) ? nav.accuracy : 999,
            captured_at: new Date().toISOString()
        };
        const arrival = deliveryArrival(location, stop);
        if (arrival.allowed) {
            openArrivalDialog(trip, stop, location, arrival);
            return;
        }
        showToast(arrival.message, true);
        return;
    }
    stopNavigation();
    document.querySelector('[data-tab="trips"]')?.click();
    document.getElementById("delivery-trip").value = String(trip.id);
    renderDeliveryStops();
    if (stop) document.getElementById("delivery-stop").value = String(stop.id);
    document.getElementById("delivery-location-form").scrollIntoView({ behavior: "smooth", block: "start" });
}

// Demo for supervisors: drives the calculated route without moving the device.
function navToggleSimulation() {
    const button = document.getElementById("nav-simulate");
    if (nav.simTimer) {
        clearInterval(nav.simTimer);
        nav.simTimer = null;
        button.textContent = "Simular";
        return;
    }
    const path = nav.steps.slice(nav.stepIndex).flatMap((step) => step.path);
    let segment = 0;
    let offset = 0;
    button.textContent = "Detener";
    nav.following = true;
    nav.simTimer = setInterval(() => {
        let advance = 30;
        while (segment < path.length - 1) {
            const length = navDistance(path[segment], path[segment + 1]);
            if (offset + advance <= length) { offset += advance; break; }
            advance -= length - offset;
            offset = 0;
            segment += 1;
        }
        if (segment >= path.length - 1) {
            clearInterval(nav.simTimer);
            nav.simTimer = null;
            button.textContent = "Simular";
            onNavPosition(path[path.length - 1], null, 5);
            return;
        }
        const a = path[segment], b = path[segment + 1];
        const t = offset / (navDistance(a, b) || 1);
        onNavPosition({ lat: a.lat + (b.lat - a.lat) * t, lng: a.lng + (b.lng - a.lng) * t }, navBearing(a, b), 5);
    }, 600);
}

function navVoicePreference() {
    try { return localStorage.getItem("flamia.navVoice") !== "off"; } catch (_) { return true; }
}

async function navKeepScreenOn() {
    try { if (nav && "wakeLock" in navigator) nav.wakeLock = await navigator.wakeLock.request("screen"); }
    catch (_) { /* The screen may still turn off; navigation keeps working when reopened. */ }
}

document.addEventListener("DOMContentLoaded", () => {
    const card = document.querySelector("#tab-map .map-card");
    const controls = document.querySelector("#tab-map .gps-sim-controls");
    if (!card || !controls) return;
    controls.insertAdjacentHTML("afterbegin", '<button type="button" id="btn-start-nav" class="btn-small">Navegar ruta</button>');
    card.insertAdjacentHTML("beforeend", NAV_OVERLAY_HTML);
    document.getElementById("btn-start-nav").addEventListener("click", startNavigation);
    document.getElementById("nav-exit").addEventListener("click", stopNavigation);
    document.getElementById("nav-simulate").addEventListener("click", navToggleSimulation);
    document.getElementById("nav-recenter").addEventListener("click", (event) => {
        if (!nav) return;
        nav.following = true;
        event.currentTarget.hidden = true;
        if (nav.position) map.panTo(nav.position);
        map.setZoom(17);
    });
    document.getElementById("nav-voice").addEventListener("click", (event) => {
        if (!nav) return;
        nav.voice = !nav.voice;
        event.currentTarget.textContent = nav.voice ? "Voz: sí" : "Voz: no";
        try { localStorage.setItem("flamia.navVoice", nav.voice ? "on" : "off"); } catch (_) {}
        if (!nav.voice && "speechSynthesis" in window) speechSynthesis.cancel();
    });
    document.getElementById("nav-banner-action").addEventListener("click", (event) => {
        if (event.currentTarget.dataset.action === "recalculate") navRecalculate();
        else navOpenDelivery();
    });
    document.addEventListener("keydown", (event) => { if (event.key === "Escape" && nav) stopNavigation(); });
    document.addEventListener("visibilitychange", () => { if (!document.hidden && nav) navKeepScreenOn(); });
});
