/// <reference types="@sveltejs/kit" />
/// <reference no-default-lib="true"/>
/// <reference lib="esnext" />
/// <reference lib="webworker" />

declare let self: ServiceWorkerGlobalScope;

import { build, files, version } from '$service-worker';

const CACHE = `cache-${version}`;
const ASSETS = [...build, ...files, '/index.html'];

self.addEventListener('install', (event) => {
	event.waitUntil(
		caches
			.open(CACHE)
			.then((cache) => cache.addAll(ASSETS))
			.then(() => self.skipWaiting())
	);
});

self.addEventListener('activate', (event) => {
	event.waitUntil(
		caches.keys().then(async (keys) => {
			for (const key of keys) {
				if (key !== CACHE) await caches.delete(key);
			}
			self.clients.claim();
		})
	);
});

self.addEventListener('fetch', (event) => {
	if (event.request.method !== 'GET') return;

	const url = new URL(event.request.url);

	// Don't cache API calls or uploads
	if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/uploads/')) return;

	event.respondWith(
		caches.match(event.request).then((cached) => {
			if (cached) return cached;
			// For navigation requests (HTML pages), serve the cached index.html as SPA fallback
			if (event.request.mode === 'navigate') {
				return caches.match('/index.html').then((fallback) => fallback || fetch(event.request));
			}
			return fetch(event.request);
		})
	);
});
