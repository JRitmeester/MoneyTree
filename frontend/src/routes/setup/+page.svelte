<script lang="ts">
	import { goto } from '$app/navigation';
	import ErrorBanner from '$lib/components/ErrorBanner.svelte';

	let username = $state('admin');
	let password = $state('');
	let confirmPassword = $state('');
	let error = $state('');
	let loading = $state(false);

	// If the app is already set up, this page has no business being open.
	$effect(() => {
		fetch('/api/auth/setup-status')
			.then((res) => res.json())
			.then((body) => {
				if (!body.needs_setup) goto('/login');
			})
			.catch(() => {});
	});

	async function submit() {
		error = '';
		if (password.length < 8) {
			error = 'Password must be at least 8 characters';
			return;
		}
		if (password !== confirmPassword) {
			error = 'Passwords do not match';
			return;
		}
		loading = true;
		try {
			const res = await fetch('/api/auth/setup', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ username, password })
			});
			if (!res.ok) {
				const data = await res.json();
				error = typeof data.detail === 'string' ? data.detail : 'Setup failed';
				return;
			}
			goto('/');
		} catch {
			error = 'Network error';
		} finally {
			loading = false;
		}
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter') submit();
	}
</script>

<svelte:head>
	<title>MoneyTree — Setup</title>
</svelte:head>

<div class="setup-wrap">
	<div class="card">
		<h1>Welcome to MoneyTree</h1>
		<p class="intro">
			Choose a username and password to protect your finances. You can add a
			passkey later under Settings.
		</p>

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
				autocomplete="new-password"
				disabled={loading}
			/>
			<p class="hint">At least 8 characters.</p>
		</div>
		<div class="field">
			<label for="confirm-password">Confirm password</label>
			<input
				id="confirm-password"
				type="password"
				bind:value={confirmPassword}
				onkeydown={handleKeydown}
				autocomplete="new-password"
				disabled={loading}
			/>
		</div>

		<button class="btn-primary" onclick={submit} disabled={loading}>
			{loading ? 'Setting up…' : 'Create account'}
		</button>
	</div>
</div>

<style>
	.setup-wrap {
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
		margin: 0 0 0.75rem;
		font-size: 1.5rem;
		color: var(--color-accent);
		text-align: center;
	}
	.intro {
		font-size: 0.9rem;
		color: var(--color-text-muted);
		text-align: center;
		margin: 0 0 1.5rem;
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
	.hint {
		margin: 0.3rem 0 0;
		font-size: 0.75rem;
		color: var(--color-text-faint);
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
</style>
