<script lang="ts">
	import { page } from '$app/state';
	import {
		getTransaction, getTransactions, saveTransactionLineItems, updateTransaction, updateLineItem,
		linkOffset, unlinkOffset,
		formatEuro, formatDate,
		type TransactionDetail, type Transaction, type LineItemCreate
	} from '$lib/api';
	import { resolveAmount, evaluateExpression } from '$lib/calc';
	import CategoryInput from '$lib/components/CategoryInput.svelte';

	let tx: TransactionDetail | null = $state(null);
	let loading = $state(true);
	let error: string | null = $state(null);

	// Category selection
	let selectedCategory: number | null = $state(null);
	let savingCategory = $state(false);

	// Line items editing state
	let editing = $state(false);
	let editItems: { description: string; amount: string; category_id: number | null }[] = $state([]);
	let saving = $state(false);

	async function load() {
		const id = Number(page.params.id);
		loading = true;
		try {
			tx = await getTransaction(id);
			selectedCategory = tx.category_id;
		} catch (e: any) {
			error = e.message;
		} finally {
			loading = false;
		}
	}

	$effect(() => { load(); });

	async function handleCategoryChange(newCategory: number | null) {
		if (!tx || newCategory === tx.category_id) return;
		selectedCategory = newCategory;
		savingCategory = true;
		try {
			await updateTransaction(tx.id, { category_id: newCategory });
			tx.category_id = newCategory;
			await load();
		} catch (e: any) {
			error = e.message;
			selectedCategory = tx.category_id;
		} finally {
			savingCategory = false;
		}
	}

	async function handleRemainingCategoryChange(itemId: number, newCategory: number | null) {
		if (!tx) return;
		savingCategory = true;
		try {
			await updateLineItem(itemId, { category_id: newCategory });
			await load();
		} catch (e: any) {
			error = e.message;
		} finally {
			savingCategory = false;
		}
	}

	function startEditing() {
		if (!tx) return;
		editItems = tx.line_items
			.filter(li => !li.is_remaining)
			.map(li => ({
				description: li.description,
				amount: (li.amount * li.quantity).toString(),
				category_id: li.category_id,
			}));
		editing = true;
	}

	function addRow() {
		if (!editing) startEditing();
		editItems = [...editItems, { description: '', amount: '', category_id: null }];
	}

	function removeRow(index: number) {
		editItems = editItems.filter((_, i) => i !== index);
	}

	function cancelEditing() {
		editing = false;
		editItems = [];
	}

	async function saveItems() {
		if (!tx) return;
		saving = true;
		try {
			const items: LineItemCreate[] = editItems
				.filter(it => it.description.trim())
				.map((it, i) => ({
					description: it.description.trim(),
					amount: evaluateExpression(it.amount) || 0,
					quantity: 1,
					category_id: it.category_id,
					sort_order: i,
				}));
			await saveTransactionLineItems(tx.id, items);
			editing = false;
			editItems = [];
			await load();
		} finally {
			saving = false;
		}
	}

	// Computed: separate remaining from explicit items
	let explicitItems = $derived(tx?.line_items.filter(li => !li.is_remaining) ?? []);
	let remainingItem = $derived(tx?.line_items.find(li => li.is_remaining) ?? null);

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
			<label class="cat-label">Category</label>
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
	</div>

	<div class="card receipt-section">
		<h2>Receipt</h2>
		{#if tx.receipt}
			<p>Receipt attached — <a href={`/receipts/${tx.receipt.id}`}>View receipt</a></p>
		{:else}
			<p class="muted">No receipt attached yet. <a href="/receipts/new?transaction_id={tx.id}" class="add-receipt-link">Add a receipt</a></p>
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

	<div class="card">
		<h2>Line Items</h2>

		{#if editing}
			<table>
				<thead>
					<tr>
						<th>Description</th>
						<th>Category</th>
						<th class="right">Amount</th>
						<th></th>
					</tr>
				</thead>
				<tbody>
					{#each editItems as item, i}
						<tr>
							<td><input type="text" bind:value={item.description} placeholder="Description" /></td>
							<td><CategoryInput value={item.category_id} onchange={(v) => { editItems[i].category_id = v; }} placeholder="Category" /></td>
							<td><input type="text" bind:value={item.amount} class="amt-input" placeholder="0.00" onblur={() => { item.amount = resolveAmount(item.amount); }} onkeydown={(e) => { if (e.key === 'Enter') { e.preventDefault(); item.amount = resolveAmount(item.amount); }}} /></td>
							<td><button class="remove-btn" onclick={() => removeRow(i)}>x</button></td>
						</tr>
					{/each}
				</tbody>
			</table>

			{#if remainingItem}
				<div class="remaining-row-edit">
					<span class="remaining-label">Remaining</span>
					<span class="remaining-amount">{formatEuro(remainingItem.amount)}</span>
					<span class="remaining-note">Auto-calculated after save</span>
				</div>
			{/if}

			<div class="edit-actions">
				<button class="add-row-btn" onclick={addRow}>+ Add row</button>
				<div class="edit-actions-right">
					<button class="cancel-btn" onclick={cancelEditing}>Cancel</button>
					<button class="save-btn" onclick={saveItems} disabled={saving}>
						{saving ? 'Saving...' : 'Save'}
					</button>
				</div>
			</div>
		{:else}
			<table>
				<thead>
					<tr>
						<th>Description</th>
						<th>Category</th>
						<th class="right">Amount</th>
					</tr>
				</thead>
				<tbody>
					{#each explicitItems as item}
						<tr>
							<td>{item.description}</td>
							<td>
								{#if item.category_name}
									<span class="cat-badge">{item.category_name}</span>
								{:else}
									<span class="muted">-</span>
								{/if}
							</td>
							<td class="right">{formatEuro(item.amount * item.quantity)}</td>
						</tr>
					{/each}
					{#if remainingItem}
						<tr class="remaining-row">
							<td><span class="remaining-label">Remaining</span></td>
							<td>
								<div class="remaining-cat-input">
									<CategoryInput
										value={remainingItem.category_id}
										onchange={(v) => handleRemainingCategoryChange(remainingItem!.id, v)}
										placeholder="Category"
									/>
								</div>
							</td>
							<td class="right">{formatEuro(remainingItem.amount * remainingItem.quantity)}</td>
						</tr>
					{/if}
				</tbody>
				{#if tx.line_items.length > 0}
					<tfoot>
						<tr>
							<td colspan="2"><strong>Total</strong></td>
							<td class="right">
								<strong>{formatEuro(tx.line_items.reduce((s, i) => s + i.amount * i.quantity, 0))}</strong>
							</td>
						</tr>
					</tfoot>
				{/if}
			</table>

			<div class="edit-actions">
				<button class="add-row-btn" onclick={addRow}>+ Add row</button>
				{#if explicitItems.length > 0}
					<button class="edit-btn" onclick={startEditing}>Edit</button>
				{/if}
			</div>
		{/if}
	</div>
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
	.muted :global(.add-receipt-link) {
		color: #2d6a4f;
		font-style: normal;
		font-weight: 500;
	}

	/* Line items section */
	.section-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		margin-bottom: 0.75rem;
	}
	.section-header h2 { margin: 0; }

	table {
		width: 100%;
		border-collapse: collapse;
	}
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
	tfoot td {
		border-top: 2px solid #e5e7eb;
		border-bottom: none;
	}

	.cat-badge {
		display: inline-block;
		padding: 0.1rem 0.4rem;
		background: #f0fdf4;
		color: #2d6a4f;
		border-radius: 4px;
		font-size: 0.8rem;
		margin: 0.1rem 0.15rem 0.1rem 0;
	}

	/* Remaining line item styling */
	.remaining-row {
		background: #f8fafc;
		border-top: 2px dashed #d1d5db;
	}
	.remaining-label {
		color: #6b7280;
		font-style: italic;
		font-size: 0.85rem;
	}
	.remaining-cat-input {
		max-width: 250px;
	}

	.remaining-row-edit {
		display: flex;
		align-items: center;
		gap: 1rem;
		padding: 0.75rem 0.5rem;
		margin-top: 0.5rem;
		background: #f8fafc;
		border-top: 2px dashed #d1d5db;
		border-radius: 0 0 4px 4px;
	}
	.remaining-amount {
		font-weight: 500;
		font-size: 0.9rem;
	}
	.remaining-note {
		color: #9ca3af;
		font-size: 0.8rem;
		font-style: italic;
	}

	td input[type="text"], td input[type="number"] {
		width: 100%;
		padding: 0.35rem 0.5rem;
		border: 1px solid #ddd;
		border-radius: 4px;
		font-size: 0.85rem;
		box-sizing: border-box;
	}
	.amt-input { width: 90px; }

	.edit-actions {
		display: flex;
		justify-content: space-between;
		align-items: center;
		margin-top: 0.75rem;
		gap: 0.5rem;
	}
	.edit-actions-right {
		display: flex;
		gap: 0.5rem;
	}

	.edit-btn {
		padding: 0.3rem 0.75rem;
		background: #2d6a4f;
		color: white;
		border: none;
		border-radius: 4px;
		cursor: pointer;
		font-size: 0.8rem;
	}
	.add-row-btn {
		padding: 0.3rem 0.75rem;
		background: none;
		border: 1px solid #2d6a4f;
		color: #2d6a4f;
		border-radius: 4px;
		cursor: pointer;
		font-size: 0.8rem;
	}
	.save-btn {
		padding: 0.3rem 0.75rem;
		background: #2d6a4f;
		color: white;
		border: none;
		border-radius: 4px;
		cursor: pointer;
		font-size: 0.8rem;
	}
	.save-btn:disabled {
		opacity: 0.6;
		cursor: not-allowed;
	}
	.cancel-btn {
		padding: 0.3rem 0.75rem;
		background: #f5f5f5;
		border: 1px solid #ddd;
		border-radius: 4px;
		cursor: pointer;
		font-size: 0.8rem;
	}
	.remove-btn {
		background: none;
		border: none;
		color: #dc2626;
		cursor: pointer;
		font-size: 1rem;
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
