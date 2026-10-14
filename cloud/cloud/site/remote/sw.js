// The phone remote opens without a connection too: the network first, the cached app when there isn't one. Nothing
// from the relay or the laptop is cached.
const CACHE = "sa-remote";
const SHELL = ["./", "app.js", "app.css", "manifest.webmanifest", "icon-192.png", "fonts/figtree.woff2", "fonts/bricolage.woff2", "fonts/jetbrains-mono.woff2"];
self.addEventListener("install", e => e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting())));
self.addEventListener("activate", e => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", e => {
  const u = new URL(e.request.url);
  if (e.request.method !== "GET" || u.origin !== location.origin || !u.pathname.startsWith("/remote/")) return;
  e.respondWith(fetch(e.request).then(r => {
    if (r.ok) { const copy = r.clone(); caches.open(CACHE).then(c => c.put(e.request, copy)); }
    return r;
  }).catch(() => caches.match(e.request, {ignoreSearch: true})));
});
