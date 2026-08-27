<script lang="ts">
	import { page } from '$app/state';
	import {
		getTransaction, getTransactions, updateTransaction, setTransactionFlags,
		linkOffset, unlinkOffset, splitTransactionReceipt,
		formatEuro, formatDate,
		type TransactionDetail, type Transaction
	} from '$lib/api';
	import CategoryInput from '$lib/components/CategoryInput.svelte';

	let tx = $state<TransactionDetail | null>(null);
	let loading = $state(true);
	let error = $state<string | null>(null);

	// Category selection
	let selectedCategory = $state<number | null>(null);
	let savingCategory = $state(false);
	let splitting = $state(false);

	async function load() {
		const id = Number(page.params.id);
		loading = true;
		try {
			tx = await getTransaction(id);
			selectedCategory = tx.category_id ?? null;
		} catch (e: any) {
			error = e.message;
		} finally {
			loading = false;
		}
	}

	$effect(() => { load(); });

	async function handleCategoryChange(newCategory: number | null) {
		if (!tx || newCategory === selectedCategory) return;
		selectedCategory = newCategory;
		savingCategory = true;
		try {
			await updateTransaction(tx.id, { category_id: newCategory });
			tx.category_id = newCategory;
		} catch (e: any) {
			error = e.message;
			selectedCategory = tx.category_id;
		} finally {
			savingCategory = false;
		}
	}

	async function handleSplit() {
		if (!tx) return;
		splitting = true;
		try {
			const { receipt_id } = await splitTransactionReceipt(tx.id);
			window.location.href = `/receipts/${receipt_id}`;
		} catch (e: any) {
			error = e.message;
			splitting = false;
		}
	}

	// Offsets
	let offsetSearch = $state('');
	let offsetResults: Transaction[] = $state([]);
	let offsetSearching = $state(false);
	let showOffsetSearch = $state(false);
	let offsetSearchTimeout: ReturnType<typeof setTimeout>;

	let offsetTotal = $derived(tx?.offsets.reduce((s, o) => s + o.bedrag, 0) ?? 0);
	let netAmount = $derived(tx ? tx.bedrag + offsetTotal : 0); // bedrag is negative, offsets are positive

	function handleOffsetSearch(e: Event) {
		const val = (e.target as HTMLInputElement).value;
		offsetSearch = val;
		clearTimeout(offsetSearchTimeout);
		if (!val.trim()) {
			offsetResults = [];
			return;
		}
		offsetSearchTimeout = setTimeout(async () => {
			offsetSearching = true;
			try {
				const res = await getTransactions({ search: val, per_page: 10 });
				// Only show income transactions not already linked
				const linkedIds = new Set(tx?.offsets.map(o => o.id) ?? []);
				offsetResults = res.items.filter(t => t.bedrag > 0 && t.id !== tx?.id && !linkedIds.has(t.id));
			} finally {
				offsetSearching = false;
			}
		}, 300);
	}

	async function handleLinkOffset(incomeId: number) {
		if (!tx) return;
		try {
			await linkOffset(tx.id, incomeId);
			offsetSearch = '';
			offsetResults = [];
			showOffsetSearch = false;
			await load();
		} catch (e: any) {
			if (e.message?.includes('409')) {
				error = 'This transaction is already linked as an offset elsewhere.';
			} else {
				error = e.message;
			}
		}
	}

	async function handleUnlinkOffset(incomeId: number) {
		if (!tx) return;
		try {
			await unlinkOffset(tx.id, incomeId);
			await load();
		} catch (e: any) {
			error = e.message;
		}
	}
</script>

{#if loading}
	<div class="loading">Loading...</div>
{:else if error}
	<div class="error">{error}</div>
{:else if tx}
	<a href="/transactions" class="back">&larr; Back to transactions</a>

	<div class="card">
		<div class="header">
			<div>
				<h1>{tx.merchant_name || tx.naam || 'Transaction'}</h1>
				<span class="date">{formatDate(tx.datum)}</span>
			</div>
			<div class="amount" class:positive={tx.bedrag > 0} class:negative={tx.bedrag < 0}>
				{formatEuro(tx.bedrag)}
			</div>
		</div>

		<div class="category-selector">
			<span class="cat-label">Category</span>
			<div class="cat-input-wrap">
				<CategoryInput
					value={selectedCategory}
					onchange={handleCategoryChange}
					placeholder="Select category..."
				/>
			</div>
			{#if savingCategory}
				<span class="saving-indicator">Saving...</span>
			{/if}
		</div>

		<div class="details">
			<div class="row">
				<span class="label">Description</span>
				<span class="value">{tx.omschrijving}</span>
			</div>
			{#if tx.tegenrekening}
				<div class="row">
					<span class="label">Counterparty IBAN</span>
					<span class="value">{tx.tegenrekening}</span>
				</div>
			{/if}
			{#if tx.naam}
				<div class="row">
					<span class="label">Name</span>
					<span class="value">{tx.naam}</span>
				</div>
			{/if}
			<div class="row">
				<span class="label">Type</span>
				<span class="value">{tx.type} ({tx.code})</span>
			</div>
			<div class="row">
				<span class="label">Processing date</span>
				<span class="value">{formatDate(tx.verwerkingsdatum)}</span>
			</div>
			<div class="row">
				<span class="label">Balance before</span>
				<span class="value">{formatEuro(tx.saldo_voor_boeking)}</span>
			</div>
		</div>

		<div class="flags">
			<label>
				<input
					type="checkbox"
					checked={tx.is_incidental}
					onchange={async () => { if (!tx) return; tx = { ...tx, ...(await setTransactionFlags(tx.id, { is_incidental: !tx.is_incidental })) }; }}
				/>
				Incidental (one-off, excluded from structural savings capacity)
			</label>
			<label>
				<input
					type="checkbox"
					checked={tx.is_internal_transfer}
					onchange={async () => { if (!tx) return; tx = { ...tx, ...(await setTransactionFlags(tx.id, { is_internal_transfer: !tx.is_internal_transfer })) }; }}
				/>
				Internal transfer (between own accounts, excluded from income/expenses)
			</label>
		</div>
	</div>

	<div class="card receipt-section">
		<h2>Receipt</h2>
		{#if tx.receipt}
			<div class="receipt-row">
				<a href={`/receipts/${tx.receipt.id}`} class="receipt-link">View receipt &rarr;</a>
			</div>
		{:else}
			<div class="receipt-row">
				<a href="/receipts/new?transaction_id={tx.id}" class="add-receipt-link">Upload receipt</a>
				<button class="split-btn" onclick={handleSplit} disabled={splitting}>
					{splitting ? 'Opening...' : 'Split into line items →'}
				</button>
			</div>
		{/if}
	</div>

	{#if tx.offsets_expense}
		<div class="card offset-section">
			<h2>Offset</h2>
			<p>This transaction offsets:
				<a href="/transactions/{tx.offsets_expense.id}">
					{tx.offsets_expense.merchant_name || tx.offsets_expense.naam || 'Transaction'}
					— {formatEuro(tx.offsets_expense.bedrag)} ({formatDate(tx.offsets_expense.datum)})
				</a>
			</p>
		</div>
	{:else if tx.bedrag < 0}
		<div class="card offset-section">
			<h2>Offsets</h2>
			{#if tx.offsets.length > 0}
				<div class="offset-list">
					{#each tx.offsets as offset}
						<div class="offset-row">
							<a href="/transactions/{offset.id}" class="offset-link">
								{offset.merchant_name || offset.naam || 'Transaction'}
								— {formatDate(offset.datum)}
							</a>
							<span class="offset-amount positive">{formatEuro(offset.bedrag)}</span>
							<button class="offset-unlink" onclick={() => handleUnlinkOffset(offset.id)} title="Remove offset">&times;</button>
						</div>
					{/each}
					<div class="offset-net">
						<span>Net amount:</span>
						<span class="offset-net-value">{formatEuro(netAmount)}</span>
					</div>
				</div>
			{/if}

			{#if showOffsetSearch}
				<div class="offset-search">
					<input
						type="text"
						placeholder="Search income transactions..."
						value={offsetSearch}
						oninput={handleOffsetSearch}
					/>
					{#if offsetResults.length > 0}
						<div class="offset-results">
							{#each offsetResults as result}
								<button class="offset-result-row" onclick={() => handleLinkOffset(result.id)}>
									<span>{result.merchant_name || result.naam || result.omschrijving.substring(0, 40)}</span>
									<span class="positive">{formatEuro(result.bedrag)}</span>
									<span class="offset-result-date">{formatDate(result.datum)}</span>
								</button>
							{/each}
						</div>
					{:else if offsetSearch.trim() && !offsetSearching}
						<p class="muted" style="margin: 0.5rem 0 0">No income transactions found.</p>
					{/if}
					<button class="cancel-btn" style="margin-top: 0.5rem" onclick={() => { showOffsetSearch = false; offsetSearch = ''; offsetResults = []; }}>Cancel</button>
				</div>
			{:else}
				<button class="add-row-btn" onclick={() => { showOffsetSearch = true; }}>+ Link offset</button>
			{/if}
		</div>
	{/if}

{/if}

<style>
	.loading, .error {
		text-align: center;
		padding: 3rem;
	}
	.error { color: #dc2626; }
	.back {
		display: inline-block;
		margin-bottom: 1rem;
		color: #2d6a4f;
		text-decoration: none;
		font-size: 0.9rem;
	}
	.card {
		background: white;
		border-radius: 8px;
		padding: 1.5rem;
		margin-bottom: 1rem;
	}
	.header {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
	}
	h1 {
		font-size: 1.5rem;
		margin: 0;
	}
	.date {
		color: #666;
		font-size: 0.9rem;
	}
	.amount {
		font-size: 1.75rem;
		font-weight: 700;
		font-variant-numeric: tabular-nums;
	}
	.positive { color: #16a34a; }
	.negative { color: #1a1a1a; }
	.category-selector {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		margin-top: 0.75rem;
	}
	.cat-label {
		font-size: 0.85rem;
		color: #666;
		flex: 0 0 auto;
	}
	.cat-input-wrap {
		min-width: 200px;
		max-width: 350px;
		flex: 1;
	}
	.saving-indicator { font-size: 0.8rem; color: #666; }
	.details {
		margin-top: 1.25rem;
	}
	.flags {
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
		margin-top: 1rem;
		padding-top: 1rem;
		border-top: 1px solid #f0f0f0;
	}
	.flags label {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		font-size: 0.85rem;
		color: #444;
		cursor: pointer;
	}
	.flags input[type="checkbox"] {
		cursor: pointer;
	}
	.row {
		display: flex;
		padding: 0.5rem 0;
		border-bottom: 1px solid #f0f0f0;
		gap: 1rem;
	}
	.label {
		flex: 0 0 160px;
		color: #666;
		font-size: 0.85rem;
	}
	.value {
		font-size: 0.9rem;
		word-break: break-word;
	}
	h2 {
		margin: 0 0 0.5rem;
		font-size: 1.1rem;
	}
	.muted {
		color: #999;
		font-style: italic;
	}
	.receipt-row {
		display: flex;
		align-items: center;
		gap: 1rem;
		flex-wrap: wrap;
	}
	.receipt-link, .add-receipt-link {
		color: #2d6a4f;
		font-weight: 500;
		font-size: 0.9rem;
	}
	.split-btn {
		padding: 0.3rem 0.75rem;
		background: none;
		border: 1px solid #2d6a4f;
		color: #2d6a4f;
		border-radius: 4px;
		cursor: pointer;
		font-size: 0.85rem;
	}
	.split-btn:hover { background: #f0fdf4; }
	.split-btn:disabled { opacity: 0.6; cursor: not-allowed; }

	.add-row-btn {
		padding: 0.3rem 0.75rem;
		background: none;
		border: 1px solid #2d6a4f;
		color: #2d6a4f;
		border-radius: 4px;
		cursor: pointer;
		font-size: 0.8rem;
	}
	.cancel-btn {
		padding: 0.3rem 0.75rem;
		background: #f5f5f5;
		border: 1px solid #ddd;
		border-radius: 4px;
		cursor: pointer;
		font-size: 0.8rem;
	}

	/* Offsets */
	.offset-section h2 { margin-bottom: 0.75rem; }
	.offset-list { margin-bottom: 0.75rem; }
	.offset-row {
		display: flex;
		align-items: center;
		gap: 0.75rem;
		padding: 0.4rem 0;
		border-bottom: 1px solid #f0f0f0;
	}
	.offset-link {
		flex: 1;
		color: #2d6a4f;
		text-decoration: none;
		font-size: 0.9rem;
	}
	.offset-link:hover { text-decoration: underline; }
	.offset-amount { font-weight: 600; font-size: 0.9rem; }
	.offset-unlink {
		background: none;
		border: none;
		color: #9ca3af;
		cursor: pointer;
		font-size: 1.1rem;
		padding: 0;
	}
	.offset-unlink:hover { color: #dc2626; }
	.offset-net {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: 0.6rem 0 0;
		margin-top: 0.25rem;
		border-top: 2px solid #e5e7eb;
		font-weight: 600;
		font-size: 0.9rem;
	}
	.offset-net-value { font-size: 1rem; }
	.offset-search { margin-top: 0.5rem; }
	.offset-search input {
		width: 100%;
		padding: 0.4rem 0.6rem;
		border: 1px solid #ddd;
		border-radius: 6px;
		font-size: 0.9rem;
	}
	.offset-results {
		border: 1px solid #ddd;
		border-top: none;
		border-radius: 0 0 6px 6px;
		max-height: 200px;
		overflow-y: auto;
	}
	.offset-result-row {
		display: flex;
		gap: 0.75rem;
		width: 100%;
		padding: 0.5rem 0.6rem;
		background: none;
		border: none;
		border-bottom: 1px solid #f0f0f0;
		cursor: pointer;
		text-align: left;
		font-size: 0.85rem;
	}
	.offset-result-row:hover { background: #f0fdf4; }
	.offset-result-row span:first-child { flex: 1; }
	.offset-result-date { color: #999; font-size: 0.8rem; }
</style>
