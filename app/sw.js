// JARVIS Service Worker — offline shell + background sync
const CACHE    = 'jarvis-v5';
const SHELL    = ['/', '/app/', '/manifest.json'];

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE).then(c => c.addAll(SHELL).catch(() => {}))
  );
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
  const url = new URL(e.request.url);

  // Always go network-first for API calls
  if (url.pathname.startsWith('/chat') ||
      url.pathname.startsWith('/health') ||
      url.pathname.startsWith('/files') ||
      url.pathname.startsWith('/download')) {
    e.respondWith(
      fetch(e.request).catch(() =>
        new Response(JSON.stringify({
          reply: "JARVIS is offline — can't reach your PC. Check that JARVIS is running and your connection.",
          files: []
        }), { headers: { 'Content-Type': 'application/json' } })
      )
    );
    return;
  }

  // App shell — network first (so UI updates show up on a normal reload
  // instead of being silently masked by a stale cache), cache as offline
  // fallback only.
  e.respondWith(
    fetch(e.request)
      .then(res => {
        const copy = res.clone();
        caches.open(CACHE).then(c => c.put(e.request, copy)).catch(() => {});
        return res;
      })
      .catch(() => caches.match(e.request))
  );
});

// Push notifications (when JARVIS sends an alert)
self.addEventListener('push', e => {
  if (!e.data) return;
  const data = e.data.json();
  e.waitUntil(
    self.registration.showNotification(data.title || 'JARVIS', {
      body:    data.body || '',
      icon:    '/icon-192.png',
      badge:   '/icon-192.png',
      vibrate: [100, 50, 100],
      data:    { url: data.url || '/' },
    })
  );
});

self.addEventListener('notificationclick', e => {
  e.notification.close();
  e.waitUntil(clients.openWindow(e.notification.data.url || '/'));
});
