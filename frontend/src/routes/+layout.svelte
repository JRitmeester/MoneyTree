<script lang="ts">
	import '$lib/styles/tokens.css';
	import { page } from '$app/state';

	let { children, data } = $props();

	const navGroups = [
		{
			label: 'Overview',
			links: [
				{ href: '/', label: 'Dashboard' },
				{ href: '/insights', label: 'Insights' }
			]
		},
		{
			label: 'Money',
			links: [
				{ href: '/transactions', label: 'Transactions' },
				{ href: '/uncategorized', label: 'Uncategorized' },
				{ href: '/recurring', label: 'Recurring' },
				{ href: '/cashflow', label: 'Cash flow' },
				{ href: '/budget', label: 'Budget' }
			]
		},
		{
			label: 'Records',
			links: [
				{ href: '/receipts', label: 'Receipts' },
				{ href: '/categories', label: 'Categories' },
				{ href: '/import', label: 'Import' }
			]
		}
	];

	function isActive(href: string): boolean {
		return href === '/' ? page.url.pathname === '/' : page.url.pathname.startsWith(href);
	}
</script>

<svelte:head>
	<title>MoneyTree</title>
	<meta name="viewport" content="width=device-width, initial-scale=1" />
	<meta name="theme-color" content="#2d6a4f" />
	<link rel="manifest" href="/manifest.json" />
</svelte:head>

<div class="app">
	{#if data?.username}
		<nav>
			<a href="/" class="brand">MoneyTree</a>
			<div class="groups">
				{#each navGroups as group (group.label)}
					<div class="group">
						{#each group.links as link (link.href)}
							<a href={link.href} aria-current={isActive(link.href) ? 'page' : undefined}>
								{link.label}
							</a>
						{/each}
					</div>
				{/each}
			</div>
			<a href="/settings" class="settings-link" aria-current={isActive('/settings') ? 'page' : undefined}>
				Settings
			</a>
		</nav>
	{/if}
	<main>
		{@render children()}
	</main>
</div>

<style>
	:global(body) {
		margin: 0;
		font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
		background: #f5f5f5;
		color: var(--color-text);
	}
	:global(*, *::before, *::after) {
		box-sizing: border-box;
	}
	.app {
		min-height: 100vh;
	}
	nav {
		background: var(--color-accent);
		color: white;
		padding: 0.75rem 1.5rem;
		display: flex;
		align-items: center;
		gap: 2rem;
	}
	.brand {
		font-size: 1.25rem;
		font-weight: 700;
		color: white;
		text-decoration: none;
		flex-shrink: 0;
	}
	.groups {
		display: flex;
		align-items: center;
		gap: 1.5rem;
		flex: 1;
	}
	.group {
		display: flex;
		align-items: center;
		gap: 1rem;
		padding-left: 1.5rem;
		border-left: 1px solid rgba(255, 255, 255, 0.25);
	}
	.group:first-child {
		padding-left: 0;
		border-left: none;
	}
	.groups a,
	.settings-link {
		color: rgba(255, 255, 255, 0.85);
		text-decoration: none;
		font-size: 0.9rem;
		padding: 0.25rem 0;
		border-bottom: 2px solid transparent;
	}
	.groups a:hover,
	.settings-link:hover {
		color: white;
	}
	.groups a[aria-current='page'],
	.settings-link[aria-current='page'] {
		color: white;
		font-weight: 600;
		border-bottom-color: white;
	}
	.settings-link {
		flex-shrink: 0;
	}
	main {
		max-width: 1200px;
		margin: 0 auto;
		padding: 1.5rem;
	}
</style>
