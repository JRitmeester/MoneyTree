<script lang="ts">
	import { page as pageStore } from '$app/state';
	import { getTransactions, getBudgets, setTransactionFlags, formatEuro, formatDate, type Transaction, type BudgetSummary } from '$lib/api';
	import DateRangeFilter from '$lib/components/DateRangeFilter.svelte';
	import CategoryInput from '$lib/components/CategoryInput.svelte';
	import { dateRange } from '$lib/stores/dateRange';
	import { get } from 'svelte/store';

	// URL params override store (for direct links), otherwise use stored range
	const urlParams = new URLSearchParams(pageStore.url.search);
	const initialRange = get(dateRange);

	let transactions: Transaction[] = $state([]);
	let budgetPeriods: BudgetSummary[] = $state([]);
	let total = $state(0);
	let page = $state(1);
	let perPage = $state(50);
	let loading = $state(true);

	const PAGE_SIZE_OPTIONS = [20, 50, 100, 200, 500];

	let search = $state('');
	let categoryFilter: number | null = $state(null);
	let dateFrom = $state(urlParams.get('date_from') ?? initialRange.dateFrom);
	let dateTo = $state(urlParams.get('date_to') ?? initialRange.dateTo);

	let searchTimeout: ReturnType<typeof setTimeout>;

	async function load() {
		loading = true;
		try {
			const res = await getTransactions({
				page,
				per_page: perPage,
				search: search || undefined,
				category_id: categoryFilter ?? undefined,
				date_from: dateFrom || undefined,
				date_to: dateTo || undefined
			});
			transactions = res.items;
			total = res.total;
		} finally {
			loading = false;
		}
	}

	function handleSearch(e: Event) {
		const val = (e.target as HTMLInputElement).value;
		search = val;
		clearTimeout(searchTimeout);
		searchTimeout = setTimeout(() => {
			page = 1;
			load();
		}, 300);
	}

	function handleDateChange() {
		page = 1;
		load();
	}

	function applyFilters() {
		page = 1;
		load();
	}

	function nextPage() {
		if (page * perPage < total) {
			page++;
			load();
		}
	}

	function prevPage() {
		if (page > 1) {
			page--;
			load();
		}
	}

	function changePerPage(e: Event) {
		perPage = Number((e.target as HTMLSelectElement).value);
		page = 1;
		load();
	}

	$effect(() => {
		load();
		getBudgets().then(bp => { budgetPeriods = bp; });
	});

	let totalPages = $derived(Math.ceil(total / perPage));

	function isNewDate(index: number): boolean {
		if (index === 0) return false;
		return transactions[index].datum !== transactions[index - 1].datum;
	}

	async function toggleIncidental(tx: Transaction) {
		const updated = await setTransactionFlags(tx.id, { is_incidental: !tx.is_incidental });
		transactions = transactions.map((t) => (t.id === tx.id ? { ...t, is_incidental: updated.is_incidental } : t));
	}
</script>

<h1>Transactions</h1>

<div class="filters">
	<div class="filter-row">
		<input type="text" placeholder="Search transactions..." value={search} oninput={handleSearch} />
		<div class="category-filter">
			<CategoryInput value={categoryFilter} onchange={(v) => { categoryFilter = v; applyFilters(); }} placeholder="Filter by category..." />
		</div>
	</div>
	<DateRangeFilter bind:dateFrom bind:dateTo onchange={handleDateChange} periods={budgetPeriods} />
</div>

<div class="info">
	{total} transactions found
</div>

{#if loading}
	<div class="loading">Loading...</div>
{:else}
	<div class="table-wrap">
		<table>
			<thead>
				<tr>
					<th>Date</th>
					<th>Merchant</th>
					<th>Category</th>
					<th class="amount">Amount</th>
					<th class="receipt-col">Receipt</th>
				</tr>
			</thead>
			<tbody>
				{#each transactions as tx, i}
					<tr class:date-divider={isNewDate(i)} onclick={() => window.location.href = `/transactions/${tx.id}`}>
						<td class="date">{formatDate(tx.datum)}</td>
						<td class="merchant">
							{tx.merchant_name || tx.naam || tx.omschrijving.substring(0, 40)}
						</td>
						<td>
							<span class="badge">{tx.category_name || tx.categorie}</span>
							{#if tx.is_internal_transfer}
								<span class="badge transfer">transfer</span>
							{/if}
							{#if tx.is_incidental}
								<span class="badge incidental">incidental</span>
							{/if}
							{#if tx.bedrag < 0 && !tx.is_internal_transfer}
								<button
									class="flag-toggle"
									title={tx.is_incidental ? 'Unmark as incidental (one-off)' : 'Mark as incidental (one-off)'}
									onclick={(e) => { e.stopPropagation(); toggleIncidental(tx); }}
								>{tx.is_incidental ? '★' : '☆'}</button>
							{/if}
						</td>
						<td class="amount" class:positive={tx.bedrag > 0} class:negative={tx.bedrag < 0}>
							{formatEuro(tx.bedrag)}
						</td>
						<td class="receipt-col">{tx.has_receipt ? '✓' : ''}</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>

	<div class="pagination">
		<button onclick={prevPage} disabled={page <= 1}>Previous</button>
		<span>Page {page} of {totalPages}</span>
		<button onclick={nextPage} disabled={page >= totalPages}>Next</button>
		<select class="per-page-select" value={perPage} onchange={changePerPage}>
			{#each PAGE_SIZE_OPTIONS as size}
				<option value={size}>{size} per page</option>
			{/each}
		</select>
	</div>
{/if}

<style>
	h1 { color: #1a1a1a; }
	.filters {
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
		margin-bottom: 1rem;
	}
	.filter-row {
		display: flex;
		gap: 0.75rem;
		flex-wrap: wrap;
	}
	.filters input {
		padding: 0.5rem 0.75rem;
		border: 1px solid #ddd;
		border-radius: 6px;
		font-size: 0.9rem;
	}
	.filter-row input[type="text"] {
		flex: 2;
		min-width: 150px;
	}
	.category-filter {
		flex: 1;
		min-width: 150px;
	}
	.info {
		font-size: 0.85rem;
		color: #666;
		margin-bottom: 0.5rem;
	}
	.loading {
		text-align: center;
		padding: 3rem;
		color: #666;
	}
	.table-wrap {
		overflow-x: auto;
		background: white;
		border-radius: 8px;
	}
	table {
		width: 100%;
		border-collapse: collapse;
	}
	th {
		text-align: left;
		padding: 0.75rem 1rem;
		border-bottom: 2px solid #e5e7eb;
		font-size: 0.85rem;
		color: #666;
		font-weight: 600;
	}
	td {
		padding: 0.625rem 1rem;
		border-bottom: 1px solid #f0f0f0;
		font-size: 0.9rem;
	}
	tr.date-divider td {
		border-top: 2px solid #e5e7eb;
	}
	tr:hover {
		background: #f9fafb;
		cursor: pointer;
	}
	.date {
		white-space: nowrap;
		color: #666;
	}
	.merchant {
		font-weight: 500;
	}
	.amount {
		text-align: right;
		font-variant-numeric: tabular-nums;
		white-space: nowrap;
	}
	.positive { color: #16a34a; }
	.negative { color: #1a1a1a; }
	.badge {
		display: inline-block;
		padding: 0.15rem 0.5rem;
		background: #f0fdf4;
		color: #2d6a4f;
		border-radius: 4px;
		font-size: 0.8rem;
	}
	.receipt-col {
		text-align: center;
		width: 60px;
		color: #16a34a;
	}
	.badge.transfer {
		background: #eff6ff;
		color: #2563eb;
		font-size: 0.65rem;
		border-radius: 4px;
		padding: 0.05rem 0.35rem;
		margin-left: 0.35rem;
	}
	.badge.incidental {
		background: #fefce8;
		color: #a16207;
		font-size: 0.65rem;
		border-radius: 4px;
		padding: 0.05rem 0.35rem;
		margin-left: 0.35rem;
	}
	.flag-toggle {
		background: none;
		border: none;
		cursor: pointer;
		color: #a16207;
		font-size: 0.9rem;
		margin-left: 0.35rem;
	}
	.pagination {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 1rem;
		margin-top: 1rem;
	}
	.pagination button {
		padding: 0.4rem 1rem;
		background: white;
		border: 1px solid #ddd;
		border-radius: 6px;
		cursor: pointer;
		font-size: 0.85rem;
	}
	.pagination button:disabled {
		opacity: 0.4;
		cursor: not-allowed;
	}
	.pagination span {
		font-size: 0.85rem;
		color: #666;
	}
	.per-page-select {
		padding: 0.4rem 0.5rem;
		border: 1px solid #ddd;
		border-radius: 6px;
		font-size: 0.85rem;
		color: #666;
		margin-left: 0.5rem;
	}
</style>
