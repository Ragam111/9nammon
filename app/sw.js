// sw.js — LCA service worker (served from / with Service-Worker-Allowed: /)
// Policy:
//   - cache-first ONLY for the static shell assets in SHELL_ASSETS (same origin, GET)
//   - navigations: network-first, fall back to /offline.html only on network failure
//   - everything else (/api/*, /v1/*, /auth/*, non-GET, requests with auth headers,
//     cross-origin, HTML pages with user data) goes straight to the network, never cached
// HTML pages are never stored: the server injects a session token into them.
"use strict";

// SHELL_HASH is checked by tests/test_pwa.py; when shell assets change, bump CACHE_NAME
// and record the new hash (the test prints the expected value).
var SHELL_HASH = "44669cf5dcc9ca7c";
var CACHE_NAME = "lca-shell-v6";
var OFFLINE_URL = "/offline.html";
var SHELL_ASSETS = [
  "/app.css",
  "/app.js",
  "/chat.css",
  "/chat.js",
  "/highlight.js",
  "/qr.js",
  "/offline.html",
  "/icons/icon-192.png",
  "/icons/icon-512.png",
  "/icons/icon-maskable-512.png",
  "/icons/apple-touch-icon.png"
];
var PRIVATE_PREFIXES = ["/api/", "/v1/", "/auth/"];
var AUTH_HEADERS = ["authorization", "x-auth-token", "x-api-key"];

// Decide what to do with a request: "cache" | "navigate" | "bypass"
function policy(req) {
  if (req.method !== "GET") return "bypass";
  var url;
  try { url = new URL(req.url); } catch (e) { return "bypass"; }
  if (url.origin !== self.location.origin) return "bypass";
  for (var i = 0; i < PRIVATE_PREFIXES.length; i++) {
    var p = PRIVATE_PREFIXES[i];
    if (url.pathname.indexOf(p) === 0 || url.pathname === p.slice(0, -1)) return "bypass";
  }
  for (var j = 0; j < AUTH_HEADERS.length; j++) {
    if (req.headers && req.headers.has(AUTH_HEADERS[j])) return "bypass";
  }
  if (req.mode === "navigate") return "navigate";
  if (!url.search && SHELL_ASSETS.indexOf(url.pathname) !== -1) return "cache";
  return "bypass";
}
self.__lcaSwPolicy = policy;  // exposed for tests only

self.addEventListener("install", function (event) {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(function (cache) { return cache.addAll(SHELL_ASSETS); })
      .then(function () { return self.skipWaiting(); })
  );
});

self.addEventListener("activate", function (event) {
  event.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(keys.map(function (k) {
        if (k.indexOf("lca-shell-") === 0 && k !== CACHE_NAME) return caches.delete(k);
        return null;
      }));
    }).then(function () { return self.clients.claim(); })
  );
});

function cacheFirst(req) {
  return caches.open(CACHE_NAME).then(function (cache) {
    return cache.match(req).then(function (hit) {
      if (hit) return hit;
      return fetch(req).then(function (res) {
        if (res && res.ok && res.type === "basic") cache.put(req, res.clone());
        return res;
      });
    });
  });
}

function networkFirstNavigate(req) {
  // Never store the page: it may carry a session token or user data.
  return fetch(req).catch(function () {
    return caches.match(OFFLINE_URL).then(function (hit) {
      return hit || new Response("offline", { status: 503, headers: { "Content-Type": "text/plain" } });
    });
  });
}

self.addEventListener("fetch", function (event) {
  var action = policy(event.request);
  if (action === "cache") event.respondWith(cacheFirst(event.request));
  else if (action === "navigate") event.respondWith(networkFirstNavigate(event.request));
  // "bypass": do not call respondWith -> browser handles it, nothing cached
});
