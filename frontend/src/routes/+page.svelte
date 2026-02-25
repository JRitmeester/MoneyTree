<script lang="ts">
	import { goto } from '$app/navigation';
	import {
		getDashboardSummary, getByCategory, getBySubcategory, getMonthlyTrend,
		formatEuro, type DashboardSummary, type CategorySpending, type SubcategorySpending, type MonthlyTrend
	} from '$lib/api';
	import DateRangeFilter from '$lib/components/DateRangeFilter.svelte';

	let summary: DashboardSummary | null = $state(null);
	let categories: CategorySpending[] = $state([]);
	let subcategories: SubcategorySpending[] = $state([]);
	let monthlyTrend: MonthlyTrend[] = $state([]);
	let loading = $state(true);
	let selectedCategory: string | null = $state(null);
	let dateFrom = $state('');
	let dateTo = $state('');

	async function load() {
		loading = true;
		const params: { date_from?: string; date_to?: string } = {};
		if (dateFrom) params.date_from = dateFrom;
		if (dateTo) params.date_to = dateTo;

		const [s, c, t] = await Promise.all([
			getDashboardSummary(params),
			getByCategory(params),
			getMonthlyTrend(12),
		]);
		summary = s;
		categories = c;
		monthlyTrend = t;
		loading = false;
	}

	$effect(() => { load(); });

	async function selectCategory(cat: string) {
		if (selectedCategory === cat) {
			selectedCategory = null;
			subcategories = [];
			return;
		}
		selectedCategory = cat;
		const params: { categorie: string; date_from?: string; date_to?: string } = { categorie: cat };
		if (dateFrom) params.date_from = dateFrom;
		if (dateTo) params.date_to = dateTo;
		subcategories = await getBySubcategory(params);
	}

	function handleDateChange() {
		selectedCategory = null;
		subcategories = [];
		load();
	}

	// For the bar chart
	function barWidth(value: number, max: number): string {
		if (max === 0) return '0%';
		return `${(value / max) * 100}%`;
	}
</script>

<div class="dashboard">
	<div class="header">
		<h1>Dashboard</h1>
		<DateRangeFilter bind:dateFrom bind:dateTo onchange={handleDateChange} />
	</div>

	{#if loading}
		<div class="loading">Loading...</div>
	{:else if summary}
		<div class="summary-cards">
			<div class="card income">
				<div class="card-value">{formatEuro(summary.total_income)}</div>
				<div class="card-label">Income</div>
			</div>
			<div class="card expenses">
				<div class="card-value">{formatEuro(summary.total_expenses)}</div>
				<div class="card-label">Expenses</div>
			</div>
			<div class="card net" class:positive={summary.net >= 0} class:negative={summary.net < 0}>
				<div class="card-value">{formatEuro(summary.net)}</div>
				<div class="card-label">Net</div>
			</div>
			<div class="card info">
				<div class="card-value">{summary.transaction_count}</div>
				<div class="card-label">Transactions</div>
			</div>
			<div class="card info">
				<div class="card-value">{summary.receipts_attached}</div>
				<div class="card-label">Receipts</div>
			</div>
		</div>

		<div class="sections">
			<div class="section">
				<h2>Spending by Category</h2>
				{#if categories.length === 0}
					<p class="muted">No expense data yet.</p>
				{:else}
					<div class="category-list">
						{#each categories as cat}
							{@const maxTotal = categories[0]?.total || 1}
							<button
								class="category-row"
								class:selected={selectedCategory === cat.category}
								onclick={() => selectCategory(cat.category)}
							>
								<div class="cat-info">
									<span class="cat-name">{cat.category}</span>
									<span class="cat-amount">{formatEuro(cat.total)}</span>
								</div>
								<div class="bar-bg">
									<div class="bar-fill" style="width: {barWidth(cat.total, maxTotal)}"></div>
								</div>
								<span class="cat-count">{cat.count} tx</span>
							</button>

							{#if selectedCategory === cat.category}
								<div class="subcategory-panel">
									{#if subcategories.length > 0}
										{#each subcategories as sub}
											<div class="sub-row">
												<span class="sub-name">{sub.category}</span>
												<span class="sub-amount">{formatEuro(sub.total)}</span>
												<span class="sub-count">{sub.count} items</span>
											</div>
										{/each}
									{:else}
										<p class="muted">No line-item data. Attach receipts to drill down.</p>
									{/if}
									<a
										class="view-tx-link"
										href="/transactions?categorie={encodeURIComponent(cat.category)}&date_from={dateFrom}&date_to={dateTo}"
									>View {cat.count} transactions &rarr;</a>
								</div>
							{/if}
						{/each}
					</div>
				{/if}
			</div>

			<div class="section">
				<h2>Monthly Trend</h2>
				{#if monthlyTrend.length === 0}
					<p class="muted">No data yet. Import transactions first.</p>
				{:else}
					<div class="trend-table">
						<div class="trend-header">
							<span>Month</span>
							<span class="right">Income</span>
							<span class="right">Expenses</span>
							<span class="right">Net</span>
						</div>
						{#each monthlyTrend as m}
							<div class="trend-row">
								<span class="month-label">{m.month}</span>
								<span class="right income-text">{formatEuro(m.income)}</span>
								<span class="right expense-text">{formatEuro(m.expenses)}</span>
								<span class="right" class:positive={m.net >= 0} class:negative={m.net < 0}>
									{formatEuro(m.net)}
								</span>
							</div>
						{/each}
					</div>
				{/if}
			</div>
		</div>

		<div class="quick-actions">
			<button onclick={() => goto('/import')}>Import CSV</button>
			<button onclick={() => goto('/receipts/new')} class="secondary">Add Receipt</button>
			<button onclick={() => goto('/transactions')} class="secondary">View Transactions</button>
		</div>
	{/if}
</div>

<style>
	.dashboard { max-width: 100%; }
	.header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		flex-wrap: wrap;
		gap: 1rem;
		margin-bottom: 1.5rem;
	}
	h1 { margin: 0; color: #1a1a1a; }
	.loading { text-align: center; padding: 3rem; color: #666; }

	.summary-cards {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
		gap: 1rem;
		margin-bottom: 1.5rem;
	}
	.card {
		background: white;
		padding: 1.25rem;
		border-radius: 8px;
		text-align: center;
	}
	.card-value {
		font-size: 1.5rem;
		font-weight: 700;
	}
	.card-label {
		font-size: 0.8rem;
		color: #666;
		margin-top: 0.25rem;
	}
	.card.income .card-value { color: #16a34a; }
	.card.expenses .card-value { color: #dc2626; }
	.card.net .card-value { color: #2d6a4f; }
	.positive { color: #16a34a !important; }
	.negative { color: #dc2626 !important; }

	.sections {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 1.5rem;
		margin-bottom: 1.5rem;
	}
	@media (max-width: 768px) {
		.sections { grid-template-columns: 1fr; }
	}

	.section {
		background: white;
		padding: 1.5rem;
		border-radius: 8px;
	}
	h2 { margin: 0 0 1rem; font-size: 1.1rem; }
	.muted { color: #999; font-style: italic; }

	.category-list { display: flex; flex-direction: column; gap: 0.25rem; }
	.category-row {
		display: block;
		width: 100%;
		text-align: left;
		background: none;
		border: none;
		padding: 0.5rem 0.75rem;
		border-radius: 6px;
		cursor: pointer;
		font-size: 0.9rem;
	}
	.category-row:hover { background: #f5f5f5; }
	.category-row.selected { background: #f0fdf4; }
	.cat-info {
		display: flex;
		justify-content: space-between;
		margin-bottom: 0.25rem;
	}
	.cat-name { font-weight: 500; }
	.cat-amount { font-weight: 600; color: #1a1a1a; }
	.bar-bg {
		height: 6px;
		background: #e5e7eb;
		border-radius: 3px;
		margin-bottom: 0.15rem;
	}
	.bar-fill {
		height: 100%;
		background: #2d6a4f;
		border-radius: 3px;
		transition: width 0.3s;
	}
	.cat-count { font-size: 0.75rem; color: #999; }

	.subcategory-panel {
		margin-left: 1rem;
		padding: 0.5rem 0.75rem;
		border-left: 3px solid #2d6a4f;
		margin-bottom: 0.5rem;
	}
	.sub-row {
		display: flex;
		justify-content: space-between;
		padding: 0.3rem 0;
		font-size: 0.85rem;
	}
	.sub-name { flex: 1; }
	.sub-amount { font-weight: 500; margin: 0 1rem; }
	.sub-count { color: #999; font-size: 0.8rem; }
	.view-tx-link {
		display: block;
		margin-top: 0.5rem;
		font-size: 0.85rem;
		color: #2d6a4f;
		text-decoration: none;
		font-weight: 500;
	}
	.view-tx-link:hover { text-decoration: underline; }

	.trend-table { font-size: 0.9rem; }
	.trend-header {
		display: grid;
		grid-template-columns: 1fr 1fr 1fr 1fr;
		padding: 0.5rem 0;
		border-bottom: 2px solid #e5e7eb;
		font-weight: 600;
		font-size: 0.8rem;
		color: #666;
	}
	.trend-row {
		display: grid;
		grid-template-columns: 1fr 1fr 1fr 1fr;
		padding: 0.4rem 0;
		border-bottom: 1px solid #f0f0f0;
	}
	.right { text-align: right; }
	.month-label { font-weight: 500; }
	.income-text { color: #16a34a; }
	.expense-text { color: #dc2626; }

	.quick-actions {
		display: flex;
		gap: 0.75rem;
		flex-wrap: wrap;
	}
	.quick-actions button {
		padding: 0.6rem 1.5rem;
		border: none;
		border-radius: 6px;
		cursor: pointer;
		font-size: 0.9rem;
		background: #2d6a4f;
		color: white;
	}
	.quick-actions button:hover { background: #1b4332; }
	.quick-actions button.secondary {
		background: white;
		color: #2d6a4f;
		border: 2px solid #2d6a4f;
	}
	.quick-actions button.secondary:hover { background: #f0fdf4; }
</style>
