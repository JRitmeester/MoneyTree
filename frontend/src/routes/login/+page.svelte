<script lang="ts">
	import { startAuthentication } from '@simplewebauthn/browser';
	import { goto } from '$app/navigation';
	import ErrorBanner from '$lib/components/ErrorBanner.svelte';

	let username = $state('');
	let password = $state('');
	let error = $state('');
	let loading = $state(false);

	// Brand-new instance with no credentials at all: run first-time setup.
	$effect(() => {
		fetch('/api/auth/setup-status')
			.then((res) => res.json())
			.then((body) => {
				if (body.needs_setup) goto('/setup');
			})
			.catch(() => {});
	});

	async function login() {
		loading = true;
		error = '';
		try {
			const res = await fetch('/api/auth/login', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ username, password }),
			});
			if (!res.ok) {
				const data = await res.json();
				error = data.detail ?? 'Login failed';
				return;
			}
			goto('/');
		} catch {
			error = 'Network error';
		} finally {
			loading = false;
		}
	}

	async function loginWithPasskey() {
		loading = true;
		error = '';
		try {
			const optionsRes = await fetch('/api/auth/passkey/auth/begin');
			if (!optionsRes.ok) {
				error = 'Could not start passkey authentication';
				return;
			}
			const options = await optionsRes.json();
			const { challenge_token } = options;

			const credential = await startAuthentication({ optionsJSON: options });

			const verifyRes = await fetch('/api/auth/passkey/auth/complete', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ ...credential, challenge_token }),
			});
			if (!verifyRes.ok) {
				const data = await verifyRes.json();
				error = data.detail ?? 'Passkey authentication failed';
				return;
			}
			goto('/');
		} catch (e) {
			if (e instanceof Error && e.name === 'NotAllowedError') {
				error = 'Passkey authentication was cancelled';
			} else {
				error = 'Passkey authentication failed';
			}
		} finally {
			loading = false;
		}
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter') login();
	}
</script>

<svelte:head>
	<title>MoneyTree — Login</title>
</svelte:head>

<div class="login-wrap">
	<div class="card">
		<h1>MoneyTree</h1>

		{#if error}
			<ErrorBanner message={error} />
		{/if}

		<div class="field">
			<label for="username">Username</label>
			<input
				id="username"
				type="text"
				bind:value={username}
				onkeydown={handleKeydown}
				autocomplete="username"
				disabled={loading}
			/>
		</div>
		<div class="field">
			<label for="password">Password</label>
			<input
				id="password"
				type="password"
				bind:value={password}
				onkeydown={handleKeydown}
				autocomplete="current-password"
				disabled={loading}
			/>
		</div>

		<button class="btn-primary" onclick={login} disabled={loading}>
			{loading ? 'Signing in…' : 'Sign in'}
		</button>

		<div class="divider"><span>or</span></div>

		<button class="btn-passkey" onclick={loginWithPasskey} disabled={loading}>
			<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
				<path d="M12 2a5 5 0 1 0 0 10A5 5 0 0 0 12 2z"/>
				<path d="M21 21v-1a4 4 0 0 0-4-4H7a4 4 0 0 0-4 4v1"/>
			</svg>
			Sign in with passkey
		</button>
	</div>
</div>

<style>
	.login-wrap {
		min-height: 100vh;
		display: flex;
		align-items: center;
		justify-content: center;
		background: #f5f5f5;
	}
	.card {
		background: var(--color-card-bg);
		padding: 2rem;
		border-radius: var(--radius-md);
		box-shadow: 0 2px 16px rgba(0, 0, 0, 0.1);
		width: 100%;
		max-width: 360px;
	}
	h1 {
		margin: 0 0 1.5rem;
		font-size: 1.5rem;
		color: var(--color-accent);
		text-align: center;
	}
	.field {
		margin-bottom: 1rem;
	}
	label {
		display: block;
		font-size: 0.85rem;
		font-weight: 500;
		margin-bottom: 0.3rem;
		color: #444;
	}
	input {
		width: 100%;
		padding: 0.55rem 0.75rem;
		border: 1px solid #ccc;
		border-radius: 4px;
		font-size: 1rem;
		outline: none;
	}
	input:focus {
		border-color: var(--color-accent);
		box-shadow: 0 0 0 2px rgba(45, 106, 79, 0.15);
	}
	.btn-primary {
		width: 100%;
		padding: 0.65rem;
		background: var(--color-accent);
		color: white;
		border: none;
		border-radius: 4px;
		font-size: 1rem;
		cursor: pointer;
		margin-top: 0.5rem;
	}
	.btn-primary:hover:not(:disabled) {
		background: #235c43;
	}
	.btn-primary:disabled {
		opacity: 0.6;
		cursor: not-allowed;
	}
	.divider {
		display: flex;
		align-items: center;
		gap: 0.75rem;
		margin: 1.25rem 0;
		color: var(--color-text-faint);
		font-size: 0.85rem;
	}
	.divider::before,
	.divider::after {
		content: '';
		flex: 1;
		height: 1px;
		background: #e0e0e0;
	}
	.btn-passkey {
		width: 100%;
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 0.5rem;
		padding: 0.65rem;
		background: var(--color-card-bg);
		color: #333;
		border: 1px solid #ccc;
		border-radius: 4px;
		font-size: 0.95rem;
		cursor: pointer;
	}
	.btn-passkey:hover:not(:disabled) {
		background: #f5f5f5;
		border-color: var(--color-text-faint);
	}
	.btn-passkey:disabled {
		opacity: 0.6;
		cursor: not-allowed;
	}
</style>
