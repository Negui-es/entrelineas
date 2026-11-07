"use strict";
const CONFIG = __PWA_CONFIG__;
const PREFIX = "entrelineas-public-shell-";
const CACHE = PREFIX + CONFIG.version;
const PUBLIC_PATHS = [...CONFIG.assets, ...Object.values(CONFIG.offline)];
const PUBLIC_URLS = new Set(PUBLIC_PATHS.map(path => new URL(path, self.location.origin).href));

self.addEventListener("install", event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(PUBLIC_PATHS.map(path =>
    new Request(new URL(path, self.location.origin), {credentials: "omit", cache: "reload"})))));
});
self.addEventListener("activate", event => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter(key => key.startsWith(PREFIX) && key !== CACHE).map(key => caches.delete(key)));
    await self.clients.claim();
  })());
});
function language(url) {
  const prefix = new URL(url).pathname.split("/")[1];
  if (Object.hasOwn(CONFIG.offline, prefix)) return prefix;
  const preferred = (self.navigator.language || "").split("-")[0];
  return Object.hasOwn(CONFIG.offline, preferred) ? preferred : CONFIG.defaultLanguage;
}
async function offlineResponse(url) {
  const code = language(url);
  const cache = await caches.open(CACHE);
  const response = await cache.match(CONFIG.offline[code], {ignoreVary: true});
  if (!response) return Response.error();
  return new Response(await response.text(), {status: 503, headers: {
    "Content-Type": "text/html; charset=utf-8", "Content-Language": code,
    "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "default-src 'none'; style-src 'self'; img-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
  }});
}
self.addEventListener("fetch", event => {
  const request = event.request;
  if (request.method !== "GET" || new URL(request.url).origin !== self.location.origin) return;
  if (PUBLIC_URLS.has(request.url)) {
    event.respondWith(caches.open(CACHE).then(async cache => (await cache.match(request, {ignoreVary: true})) || fetch(request)));
    return;
  }
  if (request.mode === "navigate") {
    // Never cache authenticated pages, form submissions, searches or user images.
    event.respondWith((async () => {
      try {
        const response = await fetch(request);
        return [502, 504].includes(response.status) ? offlineResponse(request.url) : response;
      } catch { return offlineResponse(request.url); }
    })());
  }
});
