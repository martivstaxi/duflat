const CACHE = 'bonk-v13-ts-header';
const ASSETS = [
  '/bonk.html',
  '/bonk_manifest.json',
  '/data/bonk_hourly.json',
  '/static/bonk/icon-192.png',
  '/static/bonk/icon-512.png'
];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(ASSETS).catch(()=>{})));
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;

  // Network-first for HTML + data files so updates always reach the user
  const isData = url.pathname === '/data/bonk_hourly.json' || url.pathname === '/data/bonk_daily.json' || url.pathname === '/data/not_hourly.json';
  const isHtml = url.pathname === '/bonk.html' || url.pathname.endsWith('/bonk.html');
  if (isData || isHtml) {
    e.respondWith(
      fetch(req).then(res => {
        const copy = res.clone();
        caches.open(CACHE).then(c => c.put(req, copy));
        return res;
      }).catch(() => caches.match(req))
    );
    return;
  }

  // Cache-first for everything else
  e.respondWith(
    caches.match(req).then(cached => cached || fetch(req).then(res => {
      const copy = res.clone();
      caches.open(CACHE).then(c => c.put(req, copy));
      return res;
    }))
  );
});
