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

	// Navigation requests: network-first with SPA fallback
	if (event.request.mode === 'navigate') {
		event.respondWith(
			fetch(event.request).catch(() =>
				caches.match('/index.html').then((fallback) => fallback || new Response('Offline', { status: 503 }))
			)
		);
		return;
	}

	// Static assets: cache-first
	event.respondWith(
		caches.match(event.request).then((cached) => cached || fetch(event.request))
	);
});
