/* W5 Wallet Finder - Service Worker
   Strategy: cache-first. Loads everything into cache on install, serves offline. */

const VERSION = 'v4';
const CACHE_NAME = 'w5-finder-' + VERSION;

const ASSETS = [
  './',
  './index.html',
  './style.css',
  './app.js',
  './bip39.js',
  './ton-crypto.js',
  './ton-wallet.js',
  './ton-address.js',
  './vendor-nacl.js',
  './vendor-tonweb.js',
  './manifest.json',
  './icon-192.png',
  './icon-512.png'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => cache.addAll(ASSETS))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((names) => Promise.all(
        names
          .filter((n) => n.startsWith('w5-finder-') && n !== CACHE_NAME)
          .map((n) => caches.delete(n))
      ))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;

  // Same-origin only
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  event.respondWith(
    caches.match(req).then((cached) => {
      if (cached) return cached;
      return fetch(req).then((res) => {
        if (res && res.ok && res.type === 'basic') {
          const clone = res.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(req, clone));
        }
        return res;
      }).catch(() => {
        // offline + not cached -> fallback to index for navigation
        if (req.mode === 'navigate') return caches.match('./index.html');
        return new Response('offline', { status: 503, statusText: 'Offline' });
      });
    })
  );
});
