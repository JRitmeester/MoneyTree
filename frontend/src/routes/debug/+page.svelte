<script lang="ts">
	import { formatEuro, formatDate } from '$lib/api';

	interface VirtualReceipt {
		receipt_id: number;
		transaction_id: number;
		transaction_date: string;
		transaction_merchant: string | null;
		transaction_amount: number;
	}

	let items: VirtualReceipt[] = $state([]);
	let loading = $state(true);
	let deleting: Set<number> = $state(new Set());
	let deletingAll = $state(false);
	let message: string | null = $state(null);

	async function load() {
		loading = true;
		message = null;
		try {
			const res = await fetch('/api/debug/virtual-receipts');
			items = await res.json();
		} finally {
			loading = false;
		}
	}

	async function deleteOne(receiptId: number) {
		deleting = new Set([...deleting, receiptId]);
		try {
			await fetch(`/api/debug/virtual-receipts/${receiptId}`, { method: 'DELETE' });
			items = items.filter(i => i.receipt_id !== receiptId);
		} finally {
			deleting = new Set([...deleting].filter(id => id !== receiptId));
		}
	}

	async function deleteAll() {
		if (!confirm(`Delete all ${items.length} virtual receipts?`)) return;
		deletingAll = true;
		try {
			const res = await fetch('/api/debug/virtual-receipts', { method: 'DELETE' });
			const data = await res.json();
			message = `Deleted ${data.deleted} virtual receipts.`;
			items = [];
		} finally {
			deletingAll = false;
		}
	}

	$effect(() => { load(); });
</script>

<div class="page">
	<h1>Debug</h1>

	<section class="card">
		<div class="section-header">
			<div>
				<h2>Virtual Receipts</h2>
				<p class="description">
					These receipts were auto-created during CSV import. They have no image and contain only a
					"Remaining" line item. Deleting them removes the scaffolding without affecting the transaction.
				</p>
			</div>
			{#if items.length > 0}
				<button class="danger-btn" onclick={deleteAll} disabled={deletingAll}>
					{deletingAll ? 'Deleting...' : `Delete all ${items.length}`}
				</button>
			{/if}
		</div>

		{#if message}
			<div class="success">{message}</div>
		{/if}

		{#if loading}
			<p class="muted">Loading...</p>
		{:else if items.length === 0}
			<p class="muted">No virtual receipts found.</p>
		{:else}
			<p class="count">{items.length} virtual receipt{items.length !== 1 ? 's' : ''}</p>
			<table>
				<thead>
					<tr>
						<th>Date</th>
						<th>Merchant</th>
						<th class="right">Amount</th>
						<th></th>
					</tr>
				</thead>
				<tbody>
					{#each items as item}
						<tr>
							<td class="date">{formatDate(item.transaction_date)}</td>
							<td>
								<a href="/transactions/{item.transaction_id}" class="tx-link">
									{item.transaction_merchant || `Transaction #${item.transaction_id}`}
								</a>
							</td>
							<td class="right" class:negative={item.transaction_amount < 0} class:positive={item.transaction_amount > 0}>
								{formatEuro(item.transaction_amount)}
							</td>
							<td class="action-col">
								<button
									class="delete-btn"
									onclick={() => deleteOne(item.receipt_id)}
									disabled={deleting.has(item.receipt_id)}
								>
									{deleting.has(item.receipt_id) ? '...' : 'Delete'}
								</button>
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		{/if}
	</section>
</div>

<style>
	.page { max-width: 800px; }
	h1 { margin: 0 0 1.5rem; color: #1a1a1a; }

	.card {
		background: white;
		border-radius: 8px;
		padding: 1.5rem;
	}

	.section-header {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
		gap: 1rem;
		margin-bottom: 1rem;
	}

	h2 { margin: 0 0 0.25rem; font-size: 1.1rem; }

	.description {
		margin: 0;
		font-size: 0.85rem;
		color: #666;
		max-width: 500px;
	}

	.count {
		font-size: 0.85rem;
		color: #666;
		margin: 0 0 0.75rem;
	}

	.success {
		padding: 0.6rem 0.75rem;
		background: #f0fdf4;
		color: #166534;
		border-radius: 6px;
		font-size: 0.9rem;
		margin-bottom: 0.75rem;
	}

	.muted { color: #999; font-style: italic; font-size: 0.9rem; }

	table { width: 100%; border-collapse: collapse; }
	th {
		text-align: left;
		padding: 0.5rem;
		border-bottom: 2px solid #e5e7eb;
		font-size: 0.8rem;
		color: #666;
	}
	td {
		padding: 0.5rem;
		border-bottom: 1px solid #f0f0f0;
		font-size: 0.9rem;
	}
	.right { text-align: right; }
	.date { color: #666; font-size: 0.85rem; white-space: nowrap; }
	.action-col { text-align: right; width: 70px; }

	.positive { color: #16a34a; }
	.negative { color: #1a1a1a; }

	.tx-link { color: #1a1a1a; text-decoration: none; }
	.tx-link:hover { color: #2d6a4f; text-decoration: underline; }

	.delete-btn {
		padding: 0.2rem 0.6rem;
		background: none;
		border: 1px solid #dc2626;
		color: #dc2626;
		border-radius: 4px;
		cursor: pointer;
		font-size: 0.8rem;
	}
	.delete-btn:hover { background: #fef2f2; }
	.delete-btn:disabled { opacity: 0.5; cursor: not-allowed; }

	.danger-btn {
		padding: 0.4rem 1rem;
		background: #dc2626;
		color: white;
		border: none;
		border-radius: 6px;
		cursor: pointer;
		font-size: 0.85rem;
		white-space: nowrap;
		flex-shrink: 0;
	}
	.danger-btn:hover { background: #b91c1c; }
	.danger-btn:disabled { opacity: 0.6; cursor: not-allowed; }
</style>
