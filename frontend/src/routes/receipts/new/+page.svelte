<script lang="ts">
	import { uploadReceipt, bulkReplaceLineItems, updateReceipt, type ReceiptCreateResponse, type LineItemCreate } from '$lib/api';
	import CategoryInput from '$lib/components/CategoryInput.svelte';
	import { resolveAmount, evaluateExpression } from '$lib/calc';
	import { goto } from '$app/navigation';

	// Steps: 1=upload, 2=review OCR, 3=done
	let step = $state(1);
	let loading = $state(false);
	let error: string | null = $state(null);

	// Upload
	let file: File | null = $state(null);
	let previewUrl: string | null = $state(null);

	// OCR result
	let receiptId: number | null = $state(null);
	let receiptDate = $state('');
	let totalAmount = $state('');
	let merchantName = $state('');
	let lineItems: { description: string; amount: string; quantity: number; category: string }[] = $state([]);

	function handleFileChange(e: Event) {
		const input = e.target as HTMLInputElement;
		const f = input.files?.[0];
		if (f) {
			file = f;
			previewUrl = URL.createObjectURL(f);
		}
	}

	async function handleUpload() {
		if (!file) return;
		loading = true;
		error = null;
		try {
			const result: ReceiptCreateResponse = await uploadReceipt(file);
			receiptId = result.id;
			receiptDate = result.ocr_result.date || '';
			totalAmount = result.ocr_result.total_amount?.toString() || '';
			merchantName = result.ocr_result.merchant_name || '';
			lineItems = result.ocr_result.line_items.map((li) => ({
				description: li.description,
				amount: li.amount.toString(),
				quantity: li.quantity,
				category: '',
			}));
			step = 2;
		} catch (e: any) {
			error = e.message;
		} finally {
			loading = false;
		}
	}

	function addLineItem() {
		lineItems = [...lineItems, { description: '', amount: '0', quantity: 1, category: '' }];
	}

	function removeLineItem(index: number) {
		lineItems = lineItems.filter((_, i) => i !== index);
	}

	async function handleSave() {
		if (!receiptId) return;
		loading = true;
		error = null;
		try {
			// Update receipt metadata
			await updateReceipt(receiptId, {
				date: receiptDate || undefined,
				total_amount: totalAmount ? parseFloat(totalAmount) : undefined,
				merchant_name: merchantName || undefined,
			});

			// Save line items
			const items: LineItemCreate[] = lineItems
				.filter((li) => li.description.trim())
				.map((li) => ({
					description: li.description,
					amount: evaluateExpression(li.amount) || 0,
					quantity: li.quantity,
					category: li.category || null,
				}));

			if (items.length > 0) {
				await bulkReplaceLineItems(receiptId, items);
			}

			step = 3;
		} catch (e: any) {
			error = e.message;
		} finally {
			loading = false;
		}
	}

	let lineItemsTotal = $derived(
		lineItems.reduce((sum, li) => sum + (parseFloat(li.amount) || 0) * li.quantity, 0)
	);
</script>

<a href="/receipts" class="back">&larr; Back to receipts</a>

{#if step === 1}
	<h1>Add Receipt</h1>

	<div class="upload-area">
		{#if previewUrl}
			<img src={previewUrl} alt="Preview" class="preview" />
		{/if}
		<div class="upload-controls">
			<label class="file-btn">
				<input type="file" accept="image/*" capture="environment" onchange={handleFileChange} hidden />
				Take Photo
			</label>
			<label class="file-btn secondary">
				<input type="file" accept="image/*" onchange={handleFileChange} hidden />
				Choose File
			</label>
		</div>
		{#if file}
			<p class="filename">{file.name}</p>
			<button class="submit-btn" onclick={handleUpload} disabled={loading}>
				{loading ? 'Processing OCR...' : 'Upload & Process'}
			</button>
		{/if}
	</div>
{:else if step === 2}
	<h1>Review Receipt</h1>
	<p>Correct any OCR errors below.</p>

	<div class="review-layout">
		<div class="form-section">
			<div class="field">
				<label for="date">Date</label>
				<input id="date" type="date" bind:value={receiptDate} />
			</div>
			<div class="field">
				<label for="merchant">Merchant</label>
				<input id="merchant" type="text" bind:value={merchantName} />
			</div>
			<div class="field">
				<label for="total">Total Amount</label>
				<input id="total" type="number" step="0.01" bind:value={totalAmount} />
			</div>

			<h2>Line Items</h2>
			<div class="line-items">
				{#each lineItems as item, i}
					<div class="line-item-row">
						<input type="text" placeholder="Description" bind:value={item.description} class="desc" />
						<input type="text" placeholder="Amount" bind:value={item.amount} class="amt" onblur={() => { item.amount = resolveAmount(item.amount); }} onkeydown={(e) => { if (e.key === 'Enter') { e.preventDefault(); item.amount = resolveAmount(item.amount); }}} />
						<input type="number" min="1" bind:value={item.quantity} class="qty" />
						<div class="cat"><CategoryInput value={item.category} onchange={(v) => { item.category = v; }} placeholder="Category" /></div>
						<button class="remove-btn" onclick={() => removeLineItem(i)}>x</button>
					</div>
				{/each}
			</div>

			<div class="line-items-footer">
				<button class="add-item-btn" onclick={addLineItem}>+ Add Item</button>
				<span class="items-total">
					Items total: {new Intl.NumberFormat('nl-NL', { style: 'currency', currency: 'EUR' }).format(lineItemsTotal)}
					{#if totalAmount}
						{@const diff = lineItemsTotal - parseFloat(totalAmount)}
						{#if Math.abs(diff) > 0.01}
							<span class="diff-warning">(diff: {diff > 0 ? '+' : ''}{diff.toFixed(2)})</span>
						{:else}
							<span class="diff-ok">(matches total)</span>
						{/if}
					{/if}
				</span>
			</div>

			<button class="submit-btn" onclick={handleSave} disabled={loading}>
				{loading ? 'Saving...' : 'Save Receipt'}
			</button>
		</div>

		{#if previewUrl}
			<div class="preview-section">
				<img src={previewUrl} alt="Receipt" />
			</div>
		{/if}
	</div>
{:else}
	<div class="done">
		<h1>Receipt Saved</h1>
		<div class="done-actions">
			<button onclick={() => goto(`/receipts/${receiptId}`)}>View Receipt</button>
			<button class="secondary" onclick={() => { step = 1; file = null; previewUrl = null; }}>Add Another</button>
			<button class="secondary" onclick={() => goto('/receipts')}>Back to Receipts</button>
		</div>
	</div>
{/if}

{#if error}
	<div class="error">{error}</div>
{/if}

<style>
	.back {
		display: inline-block;
		margin-bottom: 1rem;
		color: #2d6a4f;
		text-decoration: none;
		font-size: 0.9rem;
	}
	h1 { color: #1a1a1a; }
	h2 { font-size: 1.1rem; margin-top: 1.5rem; }

	.upload-area {
		background: white;
		padding: 2rem;
		border-radius: 8px;
		text-align: center;
	}
	.preview {
		max-width: 300px;
		max-height: 300px;
		border-radius: 8px;
		margin-bottom: 1rem;
	}
	.upload-controls {
		display: flex;
		gap: 1rem;
		justify-content: center;
		margin-bottom: 1rem;
	}
	.file-btn {
		padding: 0.6rem 1.5rem;
		background: #2d6a4f;
		color: white;
		border-radius: 6px;
		cursor: pointer;
		font-size: 0.95rem;
	}
	.file-btn.secondary {
		background: white;
		color: #2d6a4f;
		border: 2px solid #2d6a4f;
	}
	.filename {
		color: #666;
		font-size: 0.85rem;
		margin: 0.5rem 0;
	}
	.submit-btn {
		padding: 0.6rem 2rem;
		background: #2d6a4f;
		color: white;
		border: none;
		border-radius: 6px;
		cursor: pointer;
		font-size: 1rem;
		margin-top: 1rem;
	}
	.submit-btn:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	.review-layout {
		display: grid;
		grid-template-columns: 1fr 300px;
		gap: 1.5rem;
		align-items: start;
	}
	@media (max-width: 768px) {
		.review-layout {
			grid-template-columns: 1fr;
		}
	}
	.form-section {
		background: white;
		padding: 1.5rem;
		border-radius: 8px;
	}
	.preview-section {
		position: sticky;
		top: 1rem;
	}
	.preview-section img {
		width: 100%;
		border-radius: 8px;
	}
	.field {
		margin-bottom: 1rem;
	}
	.field label {
		display: block;
		font-size: 0.85rem;
		color: #666;
		margin-bottom: 0.25rem;
	}
	.field input {
		width: 100%;
		padding: 0.5rem;
		border: 1px solid #ddd;
		border-radius: 6px;
		font-size: 0.95rem;
	}

	.line-items {
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
	}
	.line-item-row {
		display: flex;
		gap: 0.5rem;
		align-items: center;
	}
	.line-item-row input {
		padding: 0.4rem 0.5rem;
		border: 1px solid #ddd;
		border-radius: 4px;
		font-size: 0.9rem;
	}
	.desc { flex: 3; }
	.amt { flex: 1; min-width: 80px; }
	.qty { flex: 0 0 50px; text-align: center; }
	.cat { flex: 2; }
	.remove-btn {
		background: none;
		border: none;
		color: #dc2626;
		cursor: pointer;
		font-size: 1.1rem;
		padding: 0.25rem 0.5rem;
	}

	.line-items-footer {
		display: flex;
		justify-content: space-between;
		align-items: center;
		margin-top: 0.75rem;
	}
	.add-item-btn {
		padding: 0.35rem 0.75rem;
		background: white;
		border: 1px solid #2d6a4f;
		color: #2d6a4f;
		border-radius: 4px;
		cursor: pointer;
		font-size: 0.85rem;
	}
	.items-total {
		font-size: 0.9rem;
		color: #666;
	}
	.diff-warning { color: #dc2626; font-weight: 600; }
	.diff-ok { color: #16a34a; }

	.done {
		text-align: center;
		padding: 3rem;
	}
	.done-actions {
		display: flex;
		gap: 1rem;
		justify-content: center;
		margin-top: 1.5rem;
	}
	.done-actions button {
		padding: 0.5rem 1.5rem;
		background: #2d6a4f;
		color: white;
		border: none;
		border-radius: 6px;
		cursor: pointer;
	}
	.done-actions button.secondary {
		background: white;
		color: #2d6a4f;
		border: 2px solid #2d6a4f;
	}

	.error {
		padding: 1rem;
		background: #fef2f2;
		color: #dc2626;
		border-radius: 8px;
		margin-top: 1rem;
	}
</style>
