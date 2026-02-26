<script lang="ts">
	import { page } from '$app/state';
	import {
		getCategoryDetail, formatEuro, formatDate,
		type CategoryDetail, type SpendingLineItem
	} from '$lib/api';
	import DateRangeFilter from '$lib/components/DateRangeFilter.svelte';

	let data: CategoryDetail | null = $state(null);
	let loading = $state(true);
	let error: string | null = $state(null);
	let dateFrom = $state('');
	let dateTo = $state('');

	async function load() {
		const id = Number(page.params.id);
		loading = true;
		try {
			const params: { date_from?: string; date_to?: string } = {};
			if (dateFrom) params.date_from = dateFrom;
			if (dateTo) params.date_to = dateTo;
			data = await getCategoryDetail(id, params);
		} catch (e: any) {
			error = e.message;
		} finally {
			loading = false;
		}
	}

	$effect(() => { load(); });

	function handleDateChange() {
		load();
	}

	let explicitItems = $derived(data?.line_items.filter(li => !li.is_remaining) ?? []);
	let remainingItems = $derived(data?.line_items.filter(li => li.is_remaining) ?? []);
</script>

{#if loading}
	<div class="loading">Loading...</div>
{:else if error}
	<div class="error">{error}</div>
{:else if data}
	<a href="/" class="back">&larr; Back to dashboard</a>

	<div class="page-header">
		<div class="breadcrumb">
			{#each data.breadcrumb as crumb, i}
				{#if i > 0}
					<span class="sep">&rsaquo;</span>
				{/if}
				{#if i < data.breadcrumb.length - 1}
					<a href="/spending/category/{crumb.id}?date_from={dateFrom}&date_to={dateTo}">{crumb.name}</a>
				{:else}
					<span class="current">{crumb.name}</span>
				{/if}
			{/each}
		</div>
		<DateRangeFilter bind:dateFrom bind:dateTo onchange={handleDateChange} />
	</div>

	<div class="summary-cards">
		<div class="card">
			<div class="card-value">{formatEuro(data.total)}</div>
			<div class="card-label">Total spending</div>
		</div>
		<div class="card">
			<div class="card-value">{explicitItems.length}</div>
			<div class="card-label">Line items</div>
		</div>
		<div class="card">
			<div class="card-value">{new Set(data.line_items.map(li => li.transaction_id)).size}</div>
			<div class="card-label">Transactions</div>
		</div>
	</div>

	<div class="table-wrap">
		{#if explicitItems.length === 0 && remainingItems.length === 0}
			<p class="muted">No line items in this period.</p>
		{:else}
			<table>
				<thead>
					<tr>
						<th>Date</th>
						<th>Description</th>
						<th>Category</th>
						<th class="right">Amount</th>
						<th>Transaction</th>
					</tr>
				</thead>
				<tbody>
					{#each explicitItems as item}
						<tr>
							<td class="date">{formatDate(item.transaction_date)}</td>
							<td>{item.description}</td>
							<td>
								{#if item.category}
									<span class="cat-badge">{item.category}</span>
								{:else}
									<span class="muted">-</span>
								{/if}
							</td>
							<td class="right">{formatEuro(item.amount * item.quantity)}</td>
							<td>
								<a href="/transactions/{item.transaction_id}" class="tx-link">
									{item.transaction_merchant || 'Transaction'} ({formatEuro(item.transaction_amount)})
								</a>
							</td>
						</tr>
					{/each}
					{#if remainingItems.length > 0}
						{#each remainingItems as item}
							<tr class="remaining-row">
								<td class="date">{formatDate(item.transaction_date)}</td>
								<td><span class="remaining-label">Remaining</span></td>
								<td>
									{#if item.category}
										<span class="cat-badge">{item.category}</span>
									{:else}
										<span class="muted">-</span>
									{/if}
								</td>
								<td class="right">{formatEuro(item.amount * item.quantity)}</td>
								<td>
									<a href="/transactions/{item.transaction_id}" class="tx-link">
										{item.transaction_merchant || 'Transaction'} ({formatEuro(item.transaction_amount)})
									</a>
								</td>
							</tr>
						{/each}
					{/if}
				</tbody>
				<tfoot>
					<tr>
						<td colspan="3"><strong>Total</strong></td>
						<td class="right"><strong>{formatEuro(data.total)}</strong></td>
						<td></td>
					</tr>
				</tfoot>
			</table>
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

	.page-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		flex-wrap: wrap;
		gap: 1rem;
		margin-bottom: 1.5rem;
	}

	.breadcrumb {
		display: flex;
		align-items: center;
		gap: 0.35rem;
		font-size: 1.3rem;
		font-weight: 700;
	}
	.breadcrumb a {
		color: #2d6a4f;
		text-decoration: none;
	}
	.breadcrumb a:hover { text-decoration: underline; }
	.breadcrumb .current { color: #1a1a1a; }
	.breadcrumb .sep { color: #9ca3af; font-weight: 400; }

	.summary-cards {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
		gap: 1rem;
		margin-bottom: 1.5rem;
	}
	.card {
		background: white;
		padding: 1rem;
		border-radius: 8px;
		text-align: center;
	}
	.card-value { font-size: 1.3rem; font-weight: 700; color: #1a1a1a; }
	.card-label { font-size: 0.8rem; color: #666; margin-top: 0.15rem; }

	.table-wrap {
		background: white;
		border-radius: 8px;
		padding: 1rem;
		overflow-x: auto;
	}
	.muted { color: #999; font-style: italic; }

	table { width: 100%; border-collapse: collapse; }
	th {
		text-align: left;
		padding: 0.6rem 0.75rem;
		border-bottom: 2px solid #e5e7eb;
		font-size: 0.8rem;
		color: #666;
		font-weight: 600;
	}
	td {
		padding: 0.5rem 0.75rem;
		border-bottom: 1px solid #f0f0f0;
		font-size: 0.9rem;
	}
	.right { text-align: right; }
	.date { white-space: nowrap; color: #666; }

	.cat-badge {
		display: inline-block;
		padding: 0.1rem 0.4rem;
		background: #f0fdf4;
		color: #2d6a4f;
		border-radius: 4px;
		font-size: 0.8rem;
	}

	.tx-link {
		color: #2d6a4f;
		text-decoration: none;
		font-size: 0.85rem;
	}
	.tx-link:hover { text-decoration: underline; }

	.remaining-row {
		background: #f8fafc;
	}
	.remaining-label {
		color: #6b7280;
		font-style: italic;
		font-size: 0.85rem;
	}

	tfoot td {
		border-top: 2px solid #e5e7eb;
		border-bottom: none;
	}
</style>
