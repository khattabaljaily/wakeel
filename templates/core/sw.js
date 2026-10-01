{% load i18n %}/* Wakeel service worker: offline page, fast static assets, and push notifications. */
{% load static %}const CACHE = 'wakeel-{{ version }}';
const OFFLINE_URL = '{% url "core:offline" %}';
const PRECACHE = [OFFLINE_URL, '{% static "img/logo.svg" %}', '{% static "img/icon-192.png" %}', '{% static "img/badge-96.png" %}{% translate "']; self.addEventListener('install', (event) => { event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(PRECACHE)).then(() => self.skipWaiting())); }); self.addEventListener('activate', (event) => { event.waitUntil( caches.keys() .then((keys) => Promise.all(keys.filter((k) => k.startsWith('wakeel-') && k !== CACHE).map((k) => caches.delete(k)))) .then(() => self.clients.claim()) ); }); self.addEventListener('fetch', (event) => { const req = event.request; if (req.method !== 'GET') return; const url = new URL(req.url); // Pages: always from the network (they're live data); the offline page when there's none. if (req.mode === 'navigate') { event.respondWith(fetch(req).catch(() => caches.match(OFFLINE_URL))); return; } // Our static files (CSS, JS, fonts, images): cache first, refreshed in the background. if (url.origin === location.origin && url.pathname.startsWith('/static/')) { event.respondWith(caches.open(CACHE).then((cache) => cache.match(req).then((hit) => { const fresh = fetch(req).then((res) => { if (res.ok) cache.put(req, res.clone()); return res; }).catch(() => hit); return hit || fresh; }))); } // Everything else (API, media, CDNs) goes straight to the network. }); self.addEventListener('push', (event) => { let data = {}; try { data = event.data ? event.data.json() : {}; } catch (e) { data = { body: event.data && event.data.text() }; } event.waitUntil(self.registration.showNotification(data.title || 'وكيل', { body: data.body || '', icon: '" %}{% static "img/icon-192.png" %}',
    badge: '{% static "img/badge-96.png" %}',
    dir: 'rtl', lang: 'ar',
    tag: data.tag || undefined, renotify: !!data.tag,
    data: { url: data.url || '/app/' },
  }));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const target = new URL(event.notification.data.url || '/app/', location.origin).href;
  event.waitUntil(self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((wins) => {
    for (const w of wins) {
      if (new URL(w.url).origin === location.origin && 'focus' in w) { w.navigate(target); return w.focus(); }
    }
    return self.clients.openWindow(target);
  }));
});
