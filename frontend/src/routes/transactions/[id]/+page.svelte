<script lang="ts">
	import { page } from '$app/state';
	import {
		getTransaction, saveTransactionLineItems, updateTransaction,
		getCategories,
		formatEuro, formatDate,
		type TransactionDetail, type LineItem, type LineItemCreate, type Category
	} from '$lib/api';
	import CategoryInput from '$lib/components/CategoryInput.svelte';

	let tx: TransactionDetail | null = $state(null);
	let loading = $state(true);
	let error: string | null = $state(null);

	// Category selection
	let categories: Category[] = $state([]);
	let selectedCategory = $state('');
	let savingCategory = $state(false);

	// Line items editing state
	let editing = $state(false);
	let editItems: { description: string; amount: string; category: string }[] = $state([]);
	let saving = $state(false);

	async function load() {
		const id = Number(page.params.id);
		loading = true;
		try {
			const [txData, cats] = await Promise.all([
				getTransaction(id),
				getCategories(),
			]);
			tx = txData;
			categories = cats;
			selectedCategory = tx.categorie;
		} catch (e: any) {
			error = e.message;
		} finally {
			loading = false;
		}
	}

	$effect(() => { load(); });

	function flatCats(cats: Category[], depth = 0): { name: string; depth: number }[] {
		let result: { name: string; depth: number }[] = [];
		for (const c of cats) {
			result.push({ name: c.name, depth });
			if (c.children?.length) {
				result = result.concat(flatCats(c.children, depth + 1));
			}
		}
		return result;
	}

	async function handleCategoryChange() {
		if (!tx || selectedCategory === tx.categorie) return;
		savingCategory = true;
		try {
			await updateTransaction(tx.id, { categorie: selectedCategory });
			tx.categorie = selectedCategory;
		} catch (e: any) {
			error = e.message;
			selectedCategory = tx.categorie;
		} finally {
			savingCategory = false;
		}
	}

	function startEditing() {
		if (!tx) return;
		editItems = tx.line_items.map(li => ({
			description: li.description,
			amount: (li.amount * li.quantity).toString(),
			category: li.category || '',
		}));
		editing = true;
	}

	function addRow() {
		editItems = [...editItems, { description: '', amount: '', category: '' }];
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
					amount: parseFloat(it.amount) || 0,
					quantity: 1,
					category: it.category || null,
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
			<select bind:value={selectedCategory} onchange={handleCategoryChange} disabled={savingCategory}>
				<option value={tx.categorie}>{tx.categorie}</option>
				{#each flatCats(categories) as cat}
					{#if cat.name !== tx.categorie}
						<option value={cat.name}>{'—'.repeat(cat.depth)}{cat.depth ? ' ' : ''}{cat.name}</option>
					{/if}
				{/each}
			</select>
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
			<p class="muted">No receipt attached yet.</p>
		{/if}
	</div>

	<div class="card">
		<div class="section-header">
			<h2>Line Items</h2>
			{#if !editing}
				<button class="edit-btn" onclick={startEditing}>
					{tx.line_items.length > 0 ? 'Edit' : 'Add items'}
				</button>
			{/if}
		</div>

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
							<td><CategoryInput value={item.category} onchange={(v) => { editItems[i].category = v; }} placeholder="Category" /></td>
							<td><input type="number" step="0.01" bind:value={item.amount} class="amt-input" placeholder="0.00" /></td>
							<td><button class="remove-btn" onclick={() => removeRow(i)}>x</button></td>
						</tr>
					{/each}
				</tbody>
			</table>
			<div class="edit-actions">
				<button class="add-row-btn" onclick={addRow}>+ Add row</button>
				<div class="edit-actions-right">
					<button class="cancel-btn" onclick={cancelEditing}>Cancel</button>
					<button class="save-btn" onclick={saveItems} disabled={saving}>
						{saving ? 'Saving...' : 'Save'}
					</button>
				</div>
			</div>
		{:else if tx.line_items.length === 0}
			<p class="muted">No line items yet.</p>
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
					{#each tx.line_items as item}
						<tr>
							<td>{item.description}</td>
							<td>
								{#if item.category}
									{#each item.category.split(',').map((s) => s.trim()).filter(Boolean) as cat}
										<span class="cat-badge">{cat}</span>
									{/each}
								{:else}
									<span class="muted">-</span>
								{/if}
							</td>
							<td class="right">{formatEuro(item.amount * item.quantity)}</td>
						</tr>
					{/each}
				</tbody>
				<tfoot>
					<tr>
						<td colspan="2"><strong>Total</strong></td>
						<td class="right">
							<strong>{formatEuro(tx.line_items.reduce((s, i) => s + i.amount * i.quantity, 0))}</strong>
						</td>
					</tr>
				</tfoot>
			</table>
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
	.category-selector select {
		padding: 0.35rem 0.5rem;
		border: 1px solid #ddd;
		border-radius: 6px;
		font-size: 0.9rem;
		background: white;
		min-width: 200px;
	}
	.category-selector select:focus { outline: none; border-color: #2d6a4f; }
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
</style>
