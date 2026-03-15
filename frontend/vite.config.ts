import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vitest/config';

export default defineConfig({
	plugins: [sveltekit()],
	build: {
		cssCodeSplit: false
	},
	test: {
		environment: 'jsdom',
		include: ['src/**/*.test.ts'],
		setupFiles: ['src/tests/setup.ts'],
		alias: [{ find: /^svelte/, replacement: 'svelte' }]
	},
	resolve: {
		conditions: process.env.VITEST ? ['browser'] : []
	}
});
