import { redirect } from '@sveltejs/kit';

export const prerender = false;
export const ssr = false;

export async function load({ fetch, url }: { fetch: typeof globalThis.fetch; url: URL }) {
	if (url.pathname === '/login') return {};

	const res = await fetch('/api/auth/me');
	if (res.status === 401) {
		throw redirect(302, '/login');
	}

	const data = await res.json();
	return { username: data.username as string };
}
