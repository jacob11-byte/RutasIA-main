const STATIC_CACHE = "flamia-static-v10";
const SHELL_CACHE = "flamia-shell-v8";
const APP_SHELL = [
  "/manifest.json", "/static/logistics/style.css", "/static/logistics/app.js",
  "/static/logistics/offline.js", "/static/logistics/location.js", "/static/logistics/business.js", "/static/logistics/records.js", "/static/logistics/navigation.js",
  "/static/logistics/brand/flamia-logo.svg", "/static/logistics/brand/flamia-icon.svg"
];
self.addEventListener("install", event => {
  event.waitUntil(caches.open(STATIC_CACHE).then(cache => cache.addAll(APP_SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(
    keys.filter(key => key.startsWith("flamia-") && ![STATIC_CACHE, SHELL_CACHE].includes(key)).map(key => caches.delete(key))
  )).then(() => self.clients.claim()));
});
async function navigation(request) {
  const cache = await caches.open(SHELL_CACHE);
  let response;
  try {
    response = await fetch(request);
  } catch (_) {
    const cached = await cache.match("/");
    if (cached) return cached;
    return new Response("Abre Flamia con internet e inicia sesion antes de trabajar sin conexion.", {
      status: 503, headers: { "Content-Type": "text/plain; charset=utf-8" }
    });
  }
  try {
    const url = new URL(response.url);
    if (url.pathname.startsWith("/accounts/")) await caches.delete(SHELL_CACHE);
    else if (response.ok && response.headers.has("X-Flamia-User-ID")) {
      const previous = await cache.match("/");
      if (previous && previous.headers.get("X-Flamia-User-ID") !== response.headers.get("X-Flamia-User-ID")) await cache.delete("/");
      await cache.put("/", response.clone());
    }
  } catch (_) {
    // A storage error must never replace a successful network response with
    // a cached page belonging to an earlier session.
  }
  return response;
}
self.addEventListener("fetch", event => {
  const request = event.request;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname === "/accounts/logout/" && request.method === "POST") {
    event.respondWith(fetch(request).then(async response => {
      if (response.ok) {
        await caches.delete(SHELL_CACHE);
        const clients = await self.clients.matchAll({ type: "window" });
        clients.forEach(client => client.postMessage({ type: "FLAMIA_SESSION_ENDED" }));
      }
      return response;
    }));
    return;
  }
  if (request.method !== "GET" || url.pathname.startsWith("/api/") || url.pathname.startsWith("/accounts/") || url.pathname.startsWith("/admin/")) return;
  if (request.mode === "navigate" && url.pathname === "/") {
    event.respondWith(navigation(request)); return;
  }
  if (APP_SHELL.includes(url.pathname)) {
    event.respondWith(caches.open(STATIC_CACHE).then(async cache => {
      const cached = await cache.match(request);
      if (cached) return cached;
      const response = await fetch(request);
      if (response.ok && !response.redirected) await cache.put(request, response.clone());
      return response;
    }));
  }
});
