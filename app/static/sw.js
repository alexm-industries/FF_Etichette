/* Service worker minimo: rende l'app installabile e tiene in cache l'interfaccia.
   Le chiamate /api passano sempre dalla rete (anteprime e stampa devono essere fresche). */
const CACHE = "ff-etichette-v1";
const SHELL = ["/", "/style.css", "/app.js", "/manifest.webmanifest", "/icons/icon-192.png",
  "/fonts/BigShoulders-Bold.ttf", "/fonts/InstrumentSans-Regular.ttf", "/fonts/InstrumentSans-Bold.ttf"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});
self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.pathname.startsWith("/api/")) return;
  // rete prima, cache come riserva: dopo un aggiornamento l'app non resta vecchia
  e.respondWith(fetch(e.request).then(r => {
    const copy = r.clone();
    caches.open(CACHE).then(c => c.put(e.request, copy));
    return r;
  }).catch(() => caches.match(e.request)));
});
