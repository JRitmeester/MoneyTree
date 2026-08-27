<script lang="ts">
	import { goto } from '$app/navigation';
	import {
		logout, getVirtualReceipts, deleteAllVirtualReceipts,
		deleteAllTransactions, deleteAllBudgets, deleteAllReceipts,
		deleteAllCategories, deleteEverything,
		type VirtualReceipt
	} from '$lib/api';

	interface DangerAction {
		key: string;
		title: string;
		description: string;
		buttonLabel: string;
	}

	const DANGER_ACTIONS: DangerAction[] = [
		{
			key: 'transactions',
			title: 'All Transactions',
			description: 'Permanently delete all transactions, their linked receipts, line items, and offsets.',
			buttonLabel: 'Delete all transactions',
		},
		{
			key: 'budgets',
			title: 'All Budgets',
			description: 'Permanently delete all budget periods, budget lines, and the budget template.',
			buttonLabel: 'Delete all budgets',
		},
		{
			key: 'receipts',
			title: 'All Receipts',
			description: 'Permanently delete all receipts and their line items.',
			buttonLabel: 'Delete all receipts',
		},
		{
			key: 'categories',
			title: 'All Categories',
			description: 'Permanently delete all categories and category mappings. Clears category references on transactions and line items.',
			buttonLabel: 'Delete all categories',
		},
		{
			key: 'everything',
			title: 'Everything',
			description: 'Permanently delete ALL application data: transactions, receipts, budgets, categories, and mappings.',
			buttonLabel: 'Delete everything',
		},
	];

	const deleteFns: Record<string, () => Promise<{ deleted?: number; ok?: boolean }>> = {
		transactions: deleteAllTransactions,
		budgets: deleteAllBudgets,
		receipts: deleteAllReceipts,
		categories: deleteAllCategories,
		everything: deleteEverything,
	};

	let virtualReceipts: VirtualReceipt[] = $state([]);
	let loadingReceipts = $state(true);
	let deletingReceipts = $state(false);
	let receiptMessage: string | null = $state(null);

	let activeModal: DangerAction | null = $state(null);
	let confirmText = $state('');
	let deleting = $state(false);
	let messages: Record<string, string> = $state({});

	let deleteEnabled = $derived(confirmText === 'DELETE');

	async function handleLogout() {
		await logout();
		goto('/login');
	}

	async function loadVirtualReceipts() {
		loadingReceipts = true;
		try {
			virtualReceipts = await getVirtualReceipts();
		} catch {
			virtualReceipts = [];
		} finally {
			loadingReceipts = false;
		}
	}

	async function handleDeleteVirtualReceipts() {
		deletingReceipts = true;
		receiptMessage = null;
		try {
			const result = await deleteAllVirtualReceipts();
			receiptMessage = `Deleted ${result.deleted} virtual receipts.`;
			virtualReceipts = [];
		} finally {
			deletingReceipts = false;
		}
	}

	function openModal(action: DangerAction) {
		confirmText = '';
		activeModal = action;
	}

	function closeModal() {
		activeModal = null;
		confirmText = '';
	}

	async function handleConfirmDelete() {
		if (!activeModal) return;
		const key = activeModal.key;
		deleting = true;
		try {
			const result = await deleteFns[key]();
			if ('deleted' in result) {
				messages = { ...messages, [key]: `Deleted ${result.deleted} items.` };
			} else {
				messages = { ...messages, [key]: 'All data deleted.' };
			}
			closeModal();
		} finally {
			deleting = false;
		}
	}

	$effect(() => { loadVirtualReceipts(); });
</script>

<div class="page">
	<h1>Settings</h1>

	<section class="card">
		<button class="logout-btn" onclick={handleLogout}>
			<span class="logout-icon">&rarr;</span> Logout
		</button>
	</section>

	<section class="card">
		<h2>Preferences</h2>

		<a href="/settings/security" class="settings-link">
			<span>Login & Passkeys</span>
			<span class="chevron">&rsaquo;</span>
		</a>

		<a href="/settings/sync" class="settings-link">
			<span>Sync (export / import)</span>
			<span class="chevron">&rsaquo;</span>
		</a>

		<a
			href="/settings/accounts"
			class="settings-link"
			title="Define your own IBANs so transfers between them are excluded from spending"
		>
			<span>Own Accounts</span>
			<span class="chevron">&rsaquo;</span>
		</a>
	</section>

	<section class="card">
		<h2>Data Management</h2>

		<div class="danger-item">
			<div class="danger-info">
				<h3>Virtual Receipts</h3>
				<p>Auto-created receipts with no image and only a "Remaining" line item.</p>
				{#if receiptMessage}
					<div class="success-msg">{receiptMessage}</div>
				{/if}
			</div>
			<button
				class="danger-btn"
				onclick={handleDeleteVirtualReceipts}
				disabled={deletingReceipts || virtualReceipts.length === 0}
			>
				{#if loadingReceipts}
					Loading...
				{:else if deletingReceipts}
					Deleting...
				{:else}
					Delete all {virtualReceipts.length}
				{/if}
			</button>
		</div>

		{#each DANGER_ACTIONS as action}
			<div class="danger-item">
				<div class="danger-info">
					<h3>{action.title}</h3>
					<p>{action.description}</p>
					{#if messages[action.key]}
						<div class="success-msg">{messages[action.key]}</div>
					{/if}
				</div>
				<button class="danger-btn" onclick={() => openModal(action)}>
					{action.buttonLabel}
				</button>
			</div>
		{/each}
	</section>
</div>

{#if activeModal}
	<div
		class="backdrop"
		role="button"
		tabindex="-1"
		onclick={closeModal}
		onkeydown={(e) => { if (e.key === 'Escape') closeModal(); }}
	>
		<!-- svelte-ignore a11y_click_events_have_key_events -->
		<!-- svelte-ignore a11y_no_static_element_interactions -->
		<div class="modal" onclick={(e) => e.stopPropagation()}>
			<div class="modal-header">
				<h2>{activeModal.title}</h2>
				<button class="modal-close" onclick={closeModal}>&times;</button>
			</div>
			<div class="modal-body">
				<p class="warning-text">
					{activeModal.description} This action cannot be undone.
				</p>
				<label class="confirm-label">
					Type <strong>DELETE</strong> to confirm:
					<input
						type="text"
						bind:value={confirmText}
						placeholder="DELETE"
						autocomplete="off"
						class="confirm-input"
					/>
				</label>
			</div>
			<div class="modal-footer">
				<button class="btn-secondary" onclick={closeModal}>Cancel</button>
				<button
					class="danger-btn"
					onclick={handleConfirmDelete}
					disabled={!deleteEnabled || deleting}
				>
					{deleting ? 'Deleting...' : 'Confirm'}
				</button>
			</div>
		</div>
	</div>
{/if}

<style>
	.page { max-width: 700px; }
	h1 { margin: 0 0 1.5rem; color: #1a1a1a; }

	.card {
		background: white;
		border-radius: 8px;
		padding: 1.25rem 1.5rem;
		margin-bottom: 1rem;
	}
	.card h2 {
		margin: 0 0 1rem;
		font-size: 1.1rem;
		color: #1a1a1a;
	}

	.logout-btn {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		background: none;
		border: none;
		font-size: 1rem;
		font-weight: 500;
		color: #dc2626;
		cursor: pointer;
		padding: 0.5rem 0;
	}
	.logout-btn:hover { color: #b91c1c; }
	.logout-icon { font-size: 1.2rem; }

	.settings-link {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: 0.75rem 0;
		text-decoration: none;
		color: #1a1a1a;
		font-weight: 500;
		border-top: 1px solid #f0f0f0;
	}
	.settings-link:first-of-type { border-top: none; }
	.settings-link:hover { color: #2d6a4f; }
	.chevron { color: #999; font-size: 1.3rem; }

	.danger-item {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
		gap: 1.5rem;
		padding: 1rem 0;
		border-top: 1px solid #f0f0f0;
	}
	.danger-item:first-of-type { border-top: none; }
	.danger-info { flex: 1; }
	.danger-info h3 { margin: 0 0 0.25rem; font-size: 0.95rem; }
	.danger-info p { margin: 0; font-size: 0.85rem; color: #666; }

	.danger-btn {
		padding: 0.4rem 0.9rem;
		background: #dc2626;
		color: white;
		border: none;
		border-radius: 6px;
		cursor: pointer;
		font-size: 0.85rem;
		font-weight: 500;
		white-space: nowrap;
		flex-shrink: 0;
	}
	.danger-btn:hover:not(:disabled) { background: #b91c1c; }
	.danger-btn:disabled { opacity: 0.5; cursor: not-allowed; }

	.success-msg {
		margin-top: 0.5rem;
		font-size: 0.85rem;
		color: #16a34a;
		font-weight: 500;
	}

	/* Modal */
	.backdrop {
		position: fixed;
		inset: 0;
		background: rgba(0, 0, 0, 0.4);
		display: flex;
		align-items: center;
		justify-content: center;
		z-index: 100;
	}
	.modal {
		background: white;
		border-radius: 12px;
		width: 90%;
		max-width: 480px;
		display: flex;
		flex-direction: column;
	}
	.modal-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: 1.25rem 1.5rem;
		border-bottom: 1px solid #e5e7eb;
	}
	.modal-header h2 { margin: 0; font-size: 1.1rem; }
	.modal-close {
		background: none;
		border: none;
		font-size: 1.5rem;
		cursor: pointer;
		color: #666;
		line-height: 1;
	}
	.modal-body {
		padding: 1.5rem;
	}
	.warning-text {
		margin: 0 0 1.25rem;
		color: #dc2626;
		font-size: 0.9rem;
		line-height: 1.5;
	}
	.confirm-label {
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
		font-size: 0.9rem;
		color: #333;
	}
	.confirm-input {
		padding: 0.5rem 0.75rem;
		border: 1px solid #ddd;
		border-radius: 6px;
		font-size: 0.95rem;
	}
	.confirm-input:focus {
		outline: none;
		border-color: #dc2626;
		box-shadow: 0 0 0 2px rgba(220, 38, 38, 0.15);
	}
	.modal-footer {
		display: flex;
		justify-content: flex-end;
		gap: 0.75rem;
		padding: 1rem 1.5rem;
		border-top: 1px solid #e5e7eb;
	}
	.btn-secondary {
		padding: 0.4rem 0.9rem;
		background: white;
		border: 1px solid #ddd;
		border-radius: 6px;
		cursor: pointer;
		font-size: 0.85rem;
		color: #666;
	}
	.btn-secondary:hover { background: #f5f5f5; }
</style>
