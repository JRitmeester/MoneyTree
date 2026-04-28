<script lang="ts">
	import { getReceipts, formatDate, formatEuro, imageUrl, type Receipt } from '$lib/api';
	import { goto } from '$app/navigation';

	let receipts: Receipt[] = $state([]);
	let loading = $state(true);
	let showUnmatched = $state(false);

	async function load() {
		loading = true;
		try {
			receipts = await getReceipts(showUnmatched ? { unmatched: true } : {});
		} finally {
			loading = false;
		}
	}

	function toggleFilter() {
		showUnmatched = !showUnmatched;
		load();
	}

	$effect(() => { load(); });
</script>

<div class="header">
	<h1>Receipts</h1>
	<button class="add-btn" onclick={() => goto('/receipts/new')}>+ Add Receipt</button>
</div>

<div class="filters">
	<label>
		<input type="checkbox" checked={showUnmatched} onchange={toggleFilter} />
		Unmatched only
	</label>
</div>

{#if loading}
	<div class="loading">Loading...</div>
{:else if receipts.length === 0}
	<div class="empty">
		<p>No receipts yet.</p>
		<button onclick={() => goto('/receipts/new')}>Upload your first receipt</button>
	</div>
{:else}
	<div class="grid">
		{#each receipts as receipt}
			<div
				class="card"
				role="button"
				tabindex="0"
				onclick={() => goto(`/receipts/${receipt.id}`)}
				onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); goto(`/receipts/${receipt.id}`); } }}
			>
				<div class="thumb">
					{#if receipt.image_path?.endsWith('.pdf')}
						<div class="pdf-placeholder">PDF</div>
					{:else if receipt.image_path}
						<img
							src={imageUrl(receipt.image_path)}
							alt="Receipt"
							onerror={(e) => { (e.currentTarget as HTMLImageElement).style.display = 'none'; (e.currentTarget as HTMLImageElement).nextElementSibling?.classList.remove('hidden'); }}
						/>
						<div class="no-image hidden">No image</div>
					{:else}
						<div class="no-image">No image</div>
					{/if}
				</div>
				<div class="info">
					<div class="merchant">{receipt.merchant_name || 'Unknown merchant'}</div>
					<div class="meta">
						{#if receipt.date}
							<span>{formatDate(receipt.date)}</span>
						{/if}
						{#if receipt.total_amount != null}
							<span class="amount">{formatEuro(receipt.total_amount)}</span>
						{/if}
					</div>
					<div class="status" class:linked={receipt.transaction_id != null} class:unlinked={receipt.transaction_id == null}>
						{receipt.transaction_id != null ? 'Linked' : 'Unmatched'}
					</div>
				</div>
			</div>
		{/each}
	</div>
{/if}

<style>
	.header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		margin-bottom: 1rem;
	}
	h1 { color: #1a1a1a; margin: 0; }
	.add-btn {
		padding: 0.5rem 1.25rem;
		background: #2d6a4f;
		color: white;
		border: none;
		border-radius: 6px;
		cursor: pointer;
		font-size: 0.95rem;
	}
	.filters {
		margin-bottom: 1rem;
	}
	.filters label {
		font-size: 0.9rem;
		color: #666;
		cursor: pointer;
		display: flex;
		align-items: center;
		gap: 0.5rem;
	}
	.loading, .empty {
		text-align: center;
		padding: 3rem;
		color: #666;
	}
	.empty button {
		margin-top: 1rem;
		padding: 0.5rem 1.5rem;
		background: #2d6a4f;
		color: white;
		border: none;
		border-radius: 6px;
		cursor: pointer;
	}
	.grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
		gap: 1rem;
	}
	.card {
		background: white;
		border-radius: 8px;
		overflow: hidden;
		cursor: pointer;
		transition: box-shadow 0.15s;
	}
	.card:hover {
		box-shadow: 0 2px 12px rgba(0, 0, 0, 0.1);
	}
	.thumb {
		height: 140px;
		overflow: hidden;
		background: #f5f5f5;
	}
	.thumb img {
		width: 100%;
		height: 100%;
		object-fit: cover;
	}
	.no-image {
		width: 100%;
		height: 100%;
		display: flex;
		align-items: center;
		justify-content: center;
		color: #999;
		font-size: 0.85rem;
		font-style: italic;
		background: #e5e7eb;
	}
	.pdf-placeholder {
		width: 100%;
		height: 100%;
		display: flex;
		align-items: center;
		justify-content: center;
		background: #fef3c7;
		color: #92400e;
		font-size: 1.25rem;
		font-weight: 700;
		letter-spacing: 0.05em;
	}
	.no-image.hidden {
		display: none;
	}
	.info {
		padding: 0.75rem 1rem;
	}
	.merchant {
		font-weight: 600;
		font-size: 0.95rem;
	}
	.meta {
		display: flex;
		gap: 0.75rem;
		margin-top: 0.25rem;
		font-size: 0.85rem;
		color: #666;
	}
	.amount {
		font-weight: 500;
		color: #1a1a1a;
	}
	.status {
		margin-top: 0.5rem;
		font-size: 0.8rem;
		font-weight: 500;
	}
	.linked { color: #16a34a; }
	.unlinked { color: #f59e0b; }
</style>
