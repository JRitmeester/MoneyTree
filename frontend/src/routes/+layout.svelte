<script lang="ts">
	import { startRegistration } from '@simplewebauthn/browser';
	import { goto } from '$app/navigation';

	let { children, data } = $props();

	let addingPasskey = false;

	async function logout() {
		await fetch('/api/auth/logout', { method: 'POST' });
		goto('/login');
	}

	async function addPasskey() {
		addingPasskey = true;
		try {
			const optionsRes = await fetch('/api/auth/passkey/register/begin');
			if (!optionsRes.ok) {
				alert('Could not start passkey registration');
				return;
			}
			const options = await optionsRes.json();
			const { challenge_token } = options;

			const credential = await startRegistration({ optionsJSON: options });

			const verifyRes = await fetch('/api/auth/passkey/register/complete', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ credential, challenge_token, name: 'My Passkey' }),
			});

			if (verifyRes.ok) {
				alert('Passkey added! You can now sign in with biometrics.');
			} else {
				const err = await verifyRes.json();
				alert(`Failed to add passkey: ${err.detail}`);
			}
		} catch (e) {
			if (e instanceof Error && e.name !== 'NotAllowedError') {
				alert('Failed to add passkey');
			}
		} finally {
			addingPasskey = false;
		}
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
			<div class="links">
				<a href="/budget">Budget</a>
				<a href="/transactions">Transactions</a>
				<a href="/receipts">Receipts</a>
				<a href="/categories">Categories</a>
				<a href="/uncategorized">Uncategorized</a>
				<a href="/import">Import</a>
				<a href="/debug" class="debug-link">Debug</a>
			</div>
			<div class="auth-actions">
				<button class="nav-btn" onclick={addPasskey} disabled={addingPasskey}>
					{addingPasskey ? 'Adding…' : '+ Passkey'}
				</button>
				<button class="nav-btn logout-btn" onclick={logout}>Logout</button>
			</div>
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
		flex: 1;
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
	.auth-actions {
		display: flex;
		gap: 0.5rem;
		margin-left: auto;
	}
	.nav-btn {
		background: rgba(255, 255, 255, 0.15);
		border: 1px solid rgba(255, 255, 255, 0.3);
		color: white;
		padding: 0.35rem 0.75rem;
		border-radius: 4px;
		font-size: 0.85rem;
		cursor: pointer;
	}
	.nav-btn:hover:not(:disabled) {
		background: rgba(255, 255, 255, 0.25);
	}
	.nav-btn:disabled {
		opacity: 0.6;
		cursor: not-allowed;
	}
	.logout-btn {
		background: rgba(255, 80, 80, 0.25);
		border-color: rgba(255, 80, 80, 0.4);
	}
	.logout-btn:hover {
		background: rgba(255, 80, 80, 0.4) !important;
	}
	main {
		max-width: 1200px;
		margin: 0 auto;
		padding: 1.5rem;
	}
</style>
