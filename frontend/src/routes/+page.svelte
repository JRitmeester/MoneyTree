<script lang="ts">
	import {
		getDashboardSummary, getByCategory, getCategoryChildren, getMonthlyTrend, getBudgets,
		getBudgetVsActual, getSavingsBalance, getRecurringNotices,
		formatEuro, type DashboardSummary, type CategorySpending, type MonthlyTrend, type BudgetSummary,
		type BudgetVsActualSummary, type SavingsBalance, type RecurringNotice
	} from '$lib/api';
	import DateRangeFilter from '$lib/components/DateRangeFilter.svelte';
	import BalanceChart from '$lib/components/BalanceChart.svelte';
	import SavingsCapacityPanel from '$lib/components/SavingsCapacityPanel.svelte';
	import { dateRange } from '$lib/stores/dateRange';
	import { get } from 'svelte/store';

	const initialRange = get(dateRange);
	let summary: DashboardSummary | null = $state(null);
	let categories: CategorySpending[] = $state([]);
	let monthlyTrend: MonthlyTrend[] = $state([]);
	let budgetPeriods: BudgetSummary[] = $state([]);
	let bvaData: BudgetVsActualSummary | null = $state(null);
	let savingsBalance: SavingsBalance | null = $state(null);
	let recurringNotices: RecurringNotice[] = $state([]);
	let loading = $state(true);
	let dateFrom = $state(initialRange.dateFrom);
	let dateTo = $state(initialRange.dateTo);

	// Tracks expanded categories: category_id -> loaded children
	let expandedChildren: Record<number, CategorySpending[]> = $state({});

	async function load() {
		loading = true;
		expandedChildren = {};
		const params: { date_from?: string; date_to?: string } = {};
		if (dateFrom) params.date_from = dateFrom;
		if (dateTo) params.date_to = dateTo;

		const [s, c, t, bp, sb, notices] = await Promise.all([
			getDashboardSummary(params),
			getByCategory(params),
			getMonthlyTrend(12),
			getBudgets(),
			getSavingsBalance(),
			getRecurringNotices().catch(() => []),
		]);
		summary = s;
		categories = c;
		monthlyTrend = t;
		budgetPeriods = bp;
		savingsBalance = sb;
		recurringNotices = notices;

		// Load BVA for the current budget period (contains today)
		const today = new Date().toISOString().slice(0, 10);
		const currentPeriod = bp.find(p => p.start_date <= today && p.end_date > today);
		if (currentPeriod) {
			bvaData = await getBudgetVsActual(currentPeriod.id);
		} else {
			bvaData = null;
		}

		loading = false;
	}

	$effect(() => { load(); });

	async function toggleCategory(cat: CategorySpending) {
		if (!cat.has_children || cat.category_id == null) return;

		if (expandedChildren[cat.category_id]) {
			// Collapse: remove this and all descendants
			collapseCategory(cat.category_id);
		} else {
			// Expand: fetch children
			const params: { date_from?: string; date_to?: string } = {};
			if (dateFrom) params.date_from = dateFrom;
			if (dateTo) params.date_to = dateTo;
			const children = await getCategoryChildren(cat.category_id, params);
			expandedChildren[cat.category_id] = children;
		}
	}

	function collapseCategory(catId: number) {
		const children = expandedChildren[catId];
		if (children) {
			// Recursively collapse children
			for (const child of children) {
				if (child.category_id != null && expandedChildren[child.category_id]) {
					collapseCategory(child.category_id);
				}
			}
		}
		delete expandedChildren[catId];
		expandedChildren = expandedChildren; // trigger reactivity
	}

	function handleDateChange() {
		expandedChildren = {};
		load();
	}

	function barWidth(value: number, max: number): string {
		if (max === 0) return '0%';
		return `${(value / max) * 100}%`;
	}

	function isExpanded(cat: CategorySpending): boolean {
		return cat.category_id != null && expandedChildren[cat.category_id] !== undefined;
	}

	let dataThroughLabel = $derived.by(() => {
		if (!summary?.data_through) return null;
		return new Date(summary.data_through).toLocaleDateString('en-GB', {
			day: 'numeric',
			month: 'short',
			year: 'numeric'
		});
	});

	let dataThroughStale = $derived.by(() => {
		if (!summary?.data_through) return false;
		const dataThrough = new Date(summary.data_through).getTime();
		const today = Date.now();
		const diffDays = (today - dataThrough) / 86_400_000;
		return diffDays > 7;
	});

	let savedPercent = $derived.by(() => {
		if (!summary || summary.total_income <= 0) return null;
		return Math.round((summary.net / summary.total_income) * 100);
	});

	let burndown = $derived.by(() => {
		if (!bvaData) return null;
		const flexLines = bvaData.expense_lines.filter(l => !l.is_fixed && l.category_type === 'expense');
		const budget = flexLines.reduce((s, l) => s + l.budgeted, 0);
		const actual = flexLines.reduce((s, l) => s + l.actual, 0);
		if (budget === 0) return null;

		const start = new Date(bvaData.start_date).getTime();
		const end = new Date(bvaData.end_date).getTime();
		const now = Date.now();
		const totalDays = (end - start) / 86_400_000;
		const elapsed = Math.max(0, Math.min(totalDays, (now - start) / 86_400_000));
		const expected = (budget / totalDays) * elapsed;
		const delta = expected - actual; // positive = under budget, negative = over

		return { budget, actual, expected, delta, dailyAllowance: budget / totalDays, daysLeft: totalDays - elapsed };
	});
</script>

<div class="dashboard">
	<div class="header">
		<h1>Dashboard</h1>
		<div class="header-filter">
			{#if recurringNotices.length > 0}
				<a class="recurring-notice-badge" href="/recurring">
					{recurringNotices.length} recurring notice{recurringNotices.length === 1 ? '' : 's'}
				</a>
			{/if}
			<DateRangeFilter bind:dateFrom bind:dateTo onchange={handleDateChange} periods={budgetPeriods} />
			{#if dataThroughLabel}
				<span
					class="data-through"
					class:amber={dataThroughStale}
					title={dataThroughStale ? 'Import your latest bank export' : undefined}
				>Data through {dataThroughLabel}</span>
			{/if}
		</div>
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
			{#if burndown}
				<div class="card burndown" class:positive={burndown.delta >= 0} class:negative={burndown.delta < 0}>
					<div class="card-value">{burndown.delta >= 0 ? '+' : ''}{formatEuro(burndown.delta)}</div>
					<div class="card-label">{burndown.delta >= 0 ? 'Under' : 'Over'} budget pace</div>
					<div class="card-detail">{formatEuro(burndown.actual)} / {formatEuro(burndown.budget)}</div>
				</div>
			{:else}
				<div class="card net" class:positive={summary.net >= 0} class:negative={summary.net < 0}>
					<div class="card-value">{formatEuro(summary.net)}</div>
					<div class="card-label">Net</div>
				</div>
			{/if}
			{#if savedPercent !== null}
				<div class="card saved">
					<div class="card-value">{savedPercent}%</div>
					<div class="card-label">Saved</div>
					<div class="card-detail">{formatEuro(Math.abs(summary.net))}</div>
				</div>
			{/if}
			{#if summary.transfers_net !== 0 || savingsBalance}
				<div class="card info">
					<div class="card-value">{formatEuro(summary.transfers_net)}</div>
					<div class="card-label">To savings</div>
					{#if savingsBalance}
						<div class="card-detail">
							{savingsBalance.is_net_only ? 'Net transferred' : 'Balance'}: {formatEuro(savingsBalance.balance)} · in {formatEuro(summary.transfers_in)} / out {formatEuro(summary.transfers_out)}
						</div>
					{/if}
				</div>
			{/if}
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
							{#snippet categoryBar(item: CategorySpending, maxVal: number, depth: number)}
								<button
									class="category-row"
									class:selected={isExpanded(item)}
									class:expandable={item.has_children}
									style="padding-left: {0.75 + depth * 1.25}rem"
									onclick={() => toggleCategory(item)}
								>
									<div class="cat-info">
										<span class="cat-name">
											{#if item.has_children}
												<span class="expand-icon">{isExpanded(item) ? '▼' : '▶'}</span>
											{/if}
											{item.category}
										</span>
										<span class="cat-amount">{formatEuro(item.total)}</span>
									</div>
									<div class="bar-bg">
										<div class="bar-fill" style="width: {barWidth(item.total, maxVal)}"></div>
									</div>
									<div class="cat-footer">
										<span class="cat-count">{item.count} transactions</span>
										{#if item.category_id != null}
											<a
												class="view-link"
												href="/spending/category/{item.category_id}?date_from={dateFrom}&date_to={dateTo}"
												onclick={(e) => e.stopPropagation()}
											>View &rarr;</a>
										{/if}
									</div>
								</button>

								{#if item.category_id != null && expandedChildren[item.category_id]}
									{@const children = expandedChildren[item.category_id]}
									{@const childMax = children[0]?.total || 1}
									<div class="children-panel" style="margin-left: {0.5 + depth * 0.5}rem">
										{#each children as child}
											{@render categoryBar(child, childMax, depth + 1)}
										{/each}
									</div>
								{/if}
							{/snippet}

							{@render categoryBar(cat, maxTotal, 0)}
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

		<div class="sections">
			<BalanceChart {dateFrom} {dateTo} />
			<SavingsCapacityPanel />
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

	.header-filter {
		display: flex;
		align-items: center;
		gap: 0.75rem;
		flex-wrap: wrap;
	}
	.data-through {
		font-size: 0.8rem;
		color: #666;
	}
	.data-through.amber {
		color: #a16207;
		font-weight: 600;
	}
	.recurring-notice-badge {
		font-size: 0.8rem;
		font-weight: 600;
		color: #a16207;
		background: #fef3c7;
		padding: 0.3rem 0.6rem;
		border-radius: 999px;
		text-decoration: none;
		white-space: nowrap;
	}
	.recurring-notice-badge:hover {
		background: #fde68a;
	}

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
	.card.saved .card-value { color: #2d6a4f; }
	.card.burndown .card-value { font-size: 1.3rem; }
	.card-detail { font-size: 0.75rem; color: #999; margin-top: 0.15rem; }
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

	.category-list { display: flex; flex-direction: column; gap: 0.15rem; }
	.category-row {
		display: block;
		width: 100%;
		text-align: left;
		background: none;
		border: none;
		padding: 0.5rem 0.75rem;
		border-radius: 6px;
		cursor: default;
		font-size: 0.9rem;
	}
	.category-row.expandable { cursor: pointer; }
	.category-row.expandable:hover { background: #f5f5f5; }
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
	.cat-footer {
		display: flex;
		justify-content: space-between;
		align-items: center;
	}
	.cat-count { font-size: 0.75rem; color: #999; }
	.view-link {
		font-size: 0.75rem;
		color: #2d6a4f;
		text-decoration: none;
		font-weight: 500;
		opacity: 0;
		transition: opacity 0.15s;
	}
	.category-row:hover .view-link { opacity: 1; }
	.view-link:hover { text-decoration: underline; }

	.expand-icon {
		display: inline-block;
		width: 1em;
		font-size: 0.65rem;
		color: #999;
		margin-right: 0.25rem;
	}

	.children-panel {
		border-left: 3px solid #2d6a4f;
		margin-bottom: 0.25rem;
	}

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

</style>
