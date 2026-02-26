<script lang="ts">
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import {
		getReceipt, updateReceipt, deleteReceipt, updateLineItem, deleteLineItem,
		bulkReplaceLineItems, unlinkReceipt, formatEuro, formatDate, imageUrl,
		type ReceiptDetail, type LineItemCreate
	} from '$lib/api';
	import CategoryInput from '$lib/components/CategoryInput.svelte';
	import { resolveAmount, evaluateExpression } from '$lib/calc';

	let receipt: ReceiptDetail | null = $state(null);
	let loading = $state(true);
	let error: string | null = $state(null);

	// Editing state
	let editingField: string | null = $state(null);
	let editValue = $state('');

	async function load() {
		const id = Number(page.params.id);
		loading = true;
		try {
			receipt = await getReceipt(id);
		} catch (e: any) {
			error = e.message;
		} finally {
			loading = false;
		}
	}

	$effect(() => { load(); });

	function startEdit(field: string, value: string) {
		editingField = field;
		editValue = value;
	}

	async function saveEdit() {
		if (!receipt || !editingField) return;
		const data: Record<string, any> = {};
		data[editingField] = editValue || null;
		if (editingField === 'total_amount' && editValue) {
			data[editingField] = parseFloat(editValue);
		}
		await updateReceipt(receipt.id, data);
		editingField = null;
		await load();
	}

	async function handleDelete() {
		if (!receipt || !confirm('Delete this receipt?')) return;
		await deleteReceipt(receipt.id);
		goto('/receipts');
	}

	async function handleUnlink() {
		if (!receipt) return;
		await unlinkReceipt(receipt.id);
		await load();
	}

	async function handleDeleteLineItem(id: number) {
		await deleteLineItem(id);
		await load();
	}

	// Inline line item editing
	let editingItemId: number | null = $state(null);
	let editItem = $state({ description: '', amount: '', category: '' });

	function startEditItem(item: any) {
		editingItemId = item.id;
		editItem = {
			description: item.description,
			amount: item.amount.toString(),
			category: item.category || '',
		};
	}

	async function saveEditItem() {
		if (editingItemId == null) return;
		await updateLineItem(editingItemId, {
			description: editItem.description,
			amount: evaluateExpression(editItem.amount) || 0,
			category: editItem.category || null,
		});
		editingItemId = null;
		await load();
	}
</script>

{#if loading}
	<div class="loading">Loading...</div>
{:else if error}
	<div class="error">{error}</div>
{:else if receipt}
	<a href="/receipts" class="back">&larr; Back to receipts</a>

	<div class="layout">
		<div class="details">
			<div class="card">
				<div class="card-header">
					<h1>{receipt.merchant_name || 'Receipt'}</h1>
					<button class="delete-btn" onclick={handleDelete}>Delete</button>
				</div>

				<div class="fields">
					<div class="field-row">
						<span class="label">Date</span>
						{#if editingField === 'date'}
							<input type="date" bind:value={editValue} />
							<button class="save-btn" onclick={saveEdit}>Save</button>
						{:else}
							<span class="value" onclick={() => startEdit('date', receipt?.date || '')}>
								{receipt.date ? formatDate(receipt.date) : 'Not set'}
							</span>
						{/if}
					</div>
					<div class="field-row">
						<span class="label">Total</span>
						{#if editingField === 'total_amount'}
							<input type="number" step="0.01" bind:value={editValue} />
							<button class="save-btn" onclick={saveEdit}>Save</button>
						{:else}
							<span class="value" onclick={() => startEdit('total_amount', receipt?.total_amount?.toString() || '')}>
								{receipt.total_amount != null ? formatEuro(receipt.total_amount) : 'Not set'}
							</span>
						{/if}
					</div>
					<div class="field-row">
						<span class="label">Merchant</span>
						{#if editingField === 'merchant_name'}
							<input type="text" bind:value={editValue} />
							<button class="save-btn" onclick={saveEdit}>Save</button>
						{:else}
							<span class="value" onclick={() => startEdit('merchant_name', receipt?.merchant_name || '')}>
								{receipt.merchant_name || 'Not set'}
							</span>
						{/if}
					</div>
				</div>

				{#if receipt.transaction}
					<div class="linked-tx">
						<span class="label">Linked Transaction</span>
						<a href={`/transactions/${receipt.transaction.id}`}>
							{receipt.transaction.merchant_name || receipt.transaction.naam || 'Transaction'}
							&mdash; {formatEuro(receipt.transaction.bedrag)}
							({formatDate(receipt.transaction.datum)})
						</a>
						<button class="unlink-btn" onclick={handleUnlink}>Unlink</button>
					</div>
				{:else}
					<div class="unlinked-notice">Not linked to a transaction</div>
				{/if}
			</div>

			<div class="card">
				<h2>Line Items</h2>
				{#if receipt.line_items.length === 0}
					<p class="muted">No line items.</p>
				{:else}
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
							{#each receipt.line_items as item}
								{#if editingItemId === item.id && !item.is_remaining}
									<tr>
										<td><input type="text" bind:value={editItem.description} /></td>
										<td><CategoryInput value={editItem.category} onchange={(v) => { editItem.category = v; }} placeholder="Category" /></td>
										<td><input type="text" bind:value={editItem.amount} class="amt-input" onblur={() => { editItem.amount = resolveAmount(editItem.amount); }} onkeydown={(e) => { if (e.key === 'Enter') { e.preventDefault(); editItem.amount = resolveAmount(editItem.amount); }}} /></td>
										<td>
											<button class="save-btn" onclick={saveEditItem}>Save</button>
											<button class="cancel-btn" onclick={() => { editingItemId = null; }}>Cancel</button>
										</td>
									</tr>
								{:else}
									<tr
										class:remaining-row={item.is_remaining}
										onclick={() => { if (!item.is_remaining) startEditItem(item); }}
									>
										<td>
											{#if item.is_remaining}
												<span class="remaining-label">Remaining</span>
											{:else}
												{item.description}
											{/if}
										</td>
										<td>
											{#if item.category}
												<span class="badge">{item.category}</span>
											{:else}
												<span class="muted">-</span>
											{/if}
										</td>
										<td class="right">{formatEuro(item.amount * item.quantity)}</td>
										<td>
											{#if !item.is_remaining}
												<button class="remove-btn" onclick={(e: MouseEvent) => { e.stopPropagation(); handleDeleteLineItem(item.id); }}>x</button>
											{/if}
										</td>
									</tr>
								{/if}
							{/each}
						</tbody>
						<tfoot>
							<tr>
								<td colspan="2"><strong>Total</strong></td>
								<td class="right">
									<strong>{formatEuro(receipt.line_items.reduce((s, i) => s + i.amount * i.quantity, 0))}</strong>
								</td>
								<td></td>
							</tr>
						</tfoot>
					</table>
				{/if}
			</div>
		</div>

		{#if receipt.image_path}
			<div class="image-section">
				<img src={imageUrl(receipt.image_path)} alt="Receipt" />
			</div>
		{/if}
	</div>
{/if}

<style>
	.loading { text-align: center; padding: 3rem; color: #666; }
	.error { padding: 1rem; background: #fef2f2; color: #dc2626; border-radius: 8px; }
	.back {
		display: inline-block;
		margin-bottom: 1rem;
		color: #2d6a4f;
		text-decoration: none;
		font-size: 0.9rem;
	}

	.layout {
		display: grid;
		grid-template-columns: 1fr 300px;
		gap: 1.5rem;
		align-items: start;
	}
	@media (max-width: 768px) {
		.layout { grid-template-columns: 1fr; }
	}

	.card {
		background: white;
		border-radius: 8px;
		padding: 1.5rem;
		margin-bottom: 1rem;
	}
	.card-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
	}
	h1 { margin: 0; font-size: 1.5rem; }
	h2 { margin: 0 0 1rem; font-size: 1.1rem; }

	.fields { margin-top: 1rem; }
	.field-row {
		display: flex;
		align-items: center;
		gap: 0.75rem;
		padding: 0.5rem 0;
		border-bottom: 1px solid #f0f0f0;
	}
	.label {
		flex: 0 0 100px;
		color: #666;
		font-size: 0.85rem;
	}
	.value {
		cursor: pointer;
		padding: 0.2rem 0.5rem;
		border-radius: 4px;
	}
	.value:hover { background: #f5f5f5; }

	.field-row input {
		padding: 0.35rem 0.5rem;
		border: 1px solid #ddd;
		border-radius: 4px;
		font-size: 0.9rem;
	}
	.save-btn {
		padding: 0.25rem 0.75rem;
		background: #2d6a4f;
		color: white;
		border: none;
		border-radius: 4px;
		cursor: pointer;
		font-size: 0.8rem;
	}
	.cancel-btn {
		padding: 0.25rem 0.75rem;
		background: #f5f5f5;
		border: 1px solid #ddd;
		border-radius: 4px;
		cursor: pointer;
		font-size: 0.8rem;
	}
	.delete-btn {
		padding: 0.3rem 0.75rem;
		background: white;
		border: 1px solid #dc2626;
		color: #dc2626;
		border-radius: 4px;
		cursor: pointer;
		font-size: 0.8rem;
	}
	.unlink-btn {
		padding: 0.2rem 0.5rem;
		background: none;
		border: 1px solid #999;
		border-radius: 4px;
		cursor: pointer;
		font-size: 0.75rem;
		color: #666;
		margin-left: 0.5rem;
	}

	.linked-tx {
		margin-top: 1rem;
		padding: 0.75rem;
		background: #f0fdf4;
		border-radius: 6px;
		display: flex;
		align-items: center;
		gap: 0.5rem;
		flex-wrap: wrap;
	}
	.linked-tx a { color: #2d6a4f; font-weight: 500; }
	.unlinked-notice {
		margin-top: 1rem;
		padding: 0.75rem;
		background: #fffbeb;
		border-radius: 6px;
		color: #92400e;
		font-size: 0.9rem;
	}

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
	tr:hover { background: #f9fafb; cursor: pointer; }
	.right { text-align: right; }
	.badge {
		display: inline-block;
		padding: 0.1rem 0.4rem;
		background: #f0fdf4;
		color: #2d6a4f;
		border-radius: 4px;
		font-size: 0.8rem;
		margin: 0.1rem 0.15rem 0.1rem 0;
	}
	.muted { color: #999; font-style: italic; }
	.remaining-row {
		background: #f8fafc;
		border-top: 2px dashed #d1d5db;
		cursor: default !important;
	}
	.remaining-label {
		color: #6b7280;
		font-style: italic;
		font-size: 0.85rem;
	}
	.remove-btn {
		background: none;
		border: none;
		color: #dc2626;
		cursor: pointer;
		font-size: 1rem;
	}
	.amt-input { width: 80px; }
	tfoot td {
		border-top: 2px solid #e5e7eb;
		border-bottom: none;
	}

	.image-section {
		position: sticky;
		top: 1rem;
	}
	.image-section img {
		width: 100%;
		border-radius: 8px;
	}
</style>
