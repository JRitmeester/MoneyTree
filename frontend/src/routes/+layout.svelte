<script lang="ts">
	let { children } = $props();
</script>

<svelte:head>
	<title>MoneyTree</title>
	<meta name="viewport" content="width=device-width, initial-scale=1" />
	<meta name="theme-color" content="#2d6a4f" />
	<link rel="manifest" href="/manifest.json" />
</svelte:head>

<div class="app">
	<nav>
		<a href="/" class="brand">MoneyTree</a>
		<div class="links">
			<a href="/budget">Budget</a>
			<a href="/transactions">Transactions</a>
			<a href="/receipts">Receipts</a>
			<a href="/categories">Categories</a>
			<a href="/import">Import</a>
			<a href="/debug" class="debug-link">Debug</a>
		</div>
	</nav>
	<main>
		{@render children()}
	</main>
</div>

<style>
	:global(body) {
		margin: 0;
		font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
		background: #f5f5f5;
		color: #1a1a1a;
	}
	:global(*, *::before, *::after) {
		box-sizing: border-box;
	}
	.app {
		min-height: 100vh;
	}
	nav {
		background: #2d6a4f;
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
	}
	.links {
		display: flex;
		gap: 1rem;
	}
	.links a {
		color: rgba(255, 255, 255, 0.85);
		text-decoration: none;
		font-size: 0.9rem;
	}
	.links a:hover {
		color: white;
	}
	.debug-link {
		opacity: 0.5;
		font-size: 0.8rem !important;
	}
	.debug-link:hover {
		opacity: 1;
	}
	main {
		max-width: 1200px;
		margin: 0 auto;
		padding: 1.5rem;
	}
</style>
