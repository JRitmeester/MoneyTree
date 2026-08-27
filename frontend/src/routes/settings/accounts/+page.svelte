<script lang="ts">
	import {
		getOwnAccounts, createOwnAccount, updateOwnAccount, deleteOwnAccount,
		formatEuro, type OwnAccount
	} from '$lib/api';

	let accounts: OwnAccount[] = $state([]);
	let loading = $state(true);
	let error = $state('');

	let newIban = $state('');
	let newName = $state('');
	let newType: 'checking' | 'savings' = $state('checking');
	let newStartingBalance = $state('');
	let newStartingDate = $state('');

	async function load() {
		loading = true;
		error = '';
		try {
			accounts = await getOwnAccounts();
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to load accounts';
		}
		loading = false;
	}

	$effect(() => { load(); });

	async function addAccount() {
		error = '';
		if (!newIban.trim() || !newName.trim()) {
			error = 'IBAN and name are required';
			return;
		}
		try {
			await createOwnAccount({
				iban: newIban.trim(),
				name: newName.trim(),
				account_type: newType,
				starting_balance: newStartingBalance ? parseFloat(newStartingBalance) : null,
				starting_balance_date: newStartingDate || null
			});
			newIban = '';
			newName = '';
			newStartingBalance = '';
			newStartingDate = '';
			await load();
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to create account';
		}
	}

	async function saveStartingBalance(account: OwnAccount, balance: string, dateStr: string) {
		error = '';
		try {
			await updateOwnAccount(account.id, {
				starting_balance: balance ? parseFloat(balance) : null,
				starting_balance_date: dateStr || null
			});
			await load();
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to update account';
		}
	}

	async function removeAccount(account: OwnAccount) {
		if (!confirm(`Remove ${account.name}? Transactions to this account will no longer count as internal transfers.`)) {
			return;
		}
		error = '';
		try {
			await deleteOwnAccount(account.id);
			await load();
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to delete account';
		}
	}
</script>

<div class="page">
	<a href="/settings" class="back">&larr; Settings</a>
	<h1>Own Accounts</h1>
	<p class="explainer">
		Transactions between these accounts are internal transfers: they are excluded
		from income, expenses, and savings-capacity numbers.
	</p>

	{#if error}
		<div class="error">{error}</div>
	{/if}

	{#if loading}
		<div class="loading">Loading...</div>
	{:else}
		<div class="account-list">
			{#each accounts as account (account.id)}
				<div class="account-card">
					<div class="account-head">
						<div>
							<strong>{account.name}</strong>
							<span class="account-type">{account.account_type}</span>
						</div>
						<button class="danger" onclick={() => removeAccount(account)}>Remove</button>
					</div>
					<div class="iban">{account.iban}</div>
					{#if account.account_type === 'savings'}
						<div class="starting-balance">
							<label>
								Starting balance
								<input
									type="number"
									step="0.01"
									value={account.starting_balance ?? ''}
									onchange={(e) => saveStartingBalance(
										account,
										e.currentTarget.value,
										account.starting_balance_date ?? ''
									)}
								/>
							</label>
							<label>
								as of
								<input
									type="date"
									value={account.starting_balance_date ?? ''}
									onchange={(e) => saveStartingBalance(
										account,
										String(account.starting_balance ?? ''),
										e.currentTarget.value
									)}
								/>
							</label>
							{#if account.starting_balance != null}
								<span class="hint">Currently {formatEuro(account.starting_balance)}</span>
							{:else}
								<span class="hint">Without a starting balance only net transfers are shown</span>
							{/if}
						</div>
					{/if}
				</div>
			{:else}
				<p class="muted">No accounts yet. Add your checking and savings accounts below.</p>
			{/each}
		</div>

		<div class="add-form">
			<h2>Add account</h2>
			<div class="form-row">
				<input placeholder="IBAN" bind:value={newIban} />
				<input placeholder="Name (e.g. Spaarrekening)" bind:value={newName} />
				<select bind:value={newType}>
					<option value="checking">Checking</option>
					<option value="savings">Savings</option>
				</select>
			</div>
			{#if newType === 'savings'}
				<div class="form-row">
					<input type="number" step="0.01" placeholder="Starting balance (optional)" bind:value={newStartingBalance} />
					<input type="date" bind:value={newStartingDate} />
				</div>
			{/if}
			<button class="primary" onclick={addAccount}>Add account</button>
		</div>
	{/if}
</div>

<style>
	.page { max-width: 640px; }
	.back {
		display: inline-block;
		margin-bottom: 1rem;
		color: #2d6a4f;
		text-decoration: none;
		font-size: 0.9rem;
	}
	h1 { margin: 0 0 0.5rem; color: #1a1a1a; }
	h2 { font-size: 1.05rem; margin: 0 0 0.75rem; }
	.explainer { color: #666; font-size: 0.9rem; margin-bottom: 1.25rem; }
	.error { background: #fef2f2; color: #dc2626; padding: 0.6rem 0.9rem; border-radius: 6px; margin-bottom: 1rem; font-size: 0.9rem; }
	.loading, .muted { color: #999; }
	.account-list { display: flex; flex-direction: column; gap: 0.75rem; margin-bottom: 1.5rem; }
	.account-card { background: white; border-radius: 8px; padding: 1rem 1.25rem; }
	.account-head { display: flex; justify-content: space-between; align-items: center; }
	.account-type { font-size: 0.75rem; color: #666; background: #f0f0f0; border-radius: 4px; padding: 0.1rem 0.4rem; margin-left: 0.5rem; }
	.iban { font-family: monospace; font-size: 0.85rem; color: #444; margin-top: 0.25rem; }
	.starting-balance { display: flex; gap: 0.75rem; align-items: end; flex-wrap: wrap; margin-top: 0.75rem; }
	.starting-balance label { display: flex; flex-direction: column; font-size: 0.75rem; color: #666; gap: 0.2rem; }
	.starting-balance input { padding: 0.35rem 0.5rem; border: 1px solid #ddd; border-radius: 6px; }
	.hint { font-size: 0.75rem; color: #999; }
	.add-form { background: white; border-radius: 8px; padding: 1.25rem; }
	.form-row { display: flex; gap: 0.75rem; margin-bottom: 0.75rem; flex-wrap: wrap; }
	.form-row input, .form-row select { padding: 0.45rem 0.6rem; border: 1px solid #ddd; border-radius: 6px; flex: 1; min-width: 140px; }
	button.primary { background: #2d6a4f; color: white; border: none; border-radius: 6px; padding: 0.5rem 1rem; cursor: pointer; }
	button.danger { background: none; border: 1px solid #dc2626; color: #dc2626; border-radius: 6px; padding: 0.3rem 0.7rem; cursor: pointer; font-size: 0.8rem; }
</style>
