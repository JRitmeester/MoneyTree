<script lang="ts">
	import { startRegistration } from '@simplewebauthn/browser';
	import {
		getPasskeys, deletePasskey, formatDate,
		type PasskeySummary
	} from '$lib/api';
	import PageHeader from '$lib/components/PageHeader.svelte';

	let passkeys: PasskeySummary[] = $state([]);
	let loading = $state(true);
	let addingPasskey = $state(false);
	let message: string | null = $state(null);
	let error: string | null = $state(null);

	async function load() {
		loading = true;
		try {
			passkeys = await getPasskeys();
		} finally {
			loading = false;
		}
	}

	async function addPasskey() {
		addingPasskey = true;
		error = null;
		message = null;
		try {
			const optionsRes = await fetch('/api/auth/passkey/register/begin');
			if (!optionsRes.ok) {
				error = 'Could not start passkey registration';
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
				message = 'Passkey added successfully!';
				passkeys = await getPasskeys();
			} else {
				const err = await verifyRes.json();
				error = `Failed: ${err.detail}`;
			}
		} catch (e) {
			if (e instanceof Error && e.name !== 'NotAllowedError') {
				error = 'Failed to add passkey';
			}
		} finally {
			addingPasskey = false;
		}
	}

	async function handleDelete(id: number) {
		await deletePasskey(id);
		passkeys = passkeys.filter(p => p.id !== id);
	}

	$effect(() => { load(); });
</script>

<div class="page">
	<a href="/settings" class="back">&larr; Settings</a>
	<PageHeader title="Login & Passkeys" />

	<section class="card">
		<div class="card-header">
			<h2>Passkeys</h2>
			<button class="add-btn" onclick={addPasskey} disabled={addingPasskey}>
				{addingPasskey ? 'Adding...' : '+ Add Passkey'}
			</button>
		</div>

		{#if message}
			<div class="success-msg">{message}</div>
		{/if}
		{#if error}
			<div class="error-msg">{error}</div>
		{/if}

		{#if loading}
			<p class="muted">Loading...</p>
		{:else if passkeys.length === 0}
			<p class="muted">No passkeys registered. Add one to enable biometric login.</p>
		{:else}
			<table>
				<thead>
					<tr>
						<th>Name</th>
						<th>Created</th>
						<th></th>
					</tr>
				</thead>
				<tbody>
					{#each passkeys as pk}
						<tr>
							<td class="name">{pk.name}</td>
							<td class="date">{pk.created_at ? formatDate(pk.created_at) : '-'}</td>
							<td class="actions">
								<button class="delete-btn" onclick={() => handleDelete(pk.id)}>Delete</button>
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		{/if}
	</section>
</div>

<style>
	.page { max-width: 700px; }
	.back {
		display: inline-block;
		margin-bottom: 1rem;
		color: var(--color-accent);
		text-decoration: none;
		font-size: 0.9rem;
	}

	.card {
		background: var(--color-card-bg);
		border-radius: var(--radius-md);
		padding: 1.25rem 1.5rem;
	}
	.card-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		margin-bottom: 1rem;
	}
	.card-header h2 { margin: 0; font-size: 1.1rem; }

	.add-btn {
		padding: 0.4rem 0.9rem;
		background: var(--color-accent);
		color: white;
		border: none;
		border-radius: var(--radius-sm);
		cursor: pointer;
		font-size: 0.85rem;
		font-weight: 500;
	}
	.add-btn:hover:not(:disabled) { background: #1b4332; }
	.add-btn:disabled { opacity: 0.6; cursor: not-allowed; }

	.muted { color: var(--color-text-faint); font-style: italic; }

	.success-msg {
		margin-bottom: 1rem;
		padding: 0.5rem 0.75rem;
		background: var(--color-warn-bg-green);
		color: var(--color-income);
		border-radius: var(--radius-sm);
		font-size: 0.85rem;
		font-weight: 500;
	}
	.error-msg {
		margin-bottom: 1rem;
		padding: 0.5rem 0.75rem;
		background: var(--color-warn-bg-red);
		color: var(--color-expense);
		border-radius: var(--radius-sm);
		font-size: 0.85rem;
		font-weight: 500;
	}

	table { width: 100%; border-collapse: collapse; }
	th {
		text-align: left;
		padding: 0.6rem 0.75rem;
		border-bottom: 2px solid var(--color-border-light);
		font-size: 0.8rem;
		color: var(--color-text-muted);
		font-weight: 600;
	}
	td {
		padding: 0.5rem 0.75rem;
		border-bottom: 1px solid var(--color-bg-subtle);
		font-size: 0.9rem;
	}
	.name { font-weight: 500; }
	.date { color: var(--color-text-muted); white-space: nowrap; }
	.actions { text-align: right; }

	.delete-btn {
		background: none;
		border: none;
		color: var(--color-expense);
		cursor: pointer;
		font-size: 0.85rem;
		font-weight: 500;
		padding: 0.2rem 0.5rem;
	}
	.delete-btn:hover { color: #b91c1c; text-decoration: underline; }
</style>
