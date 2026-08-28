<script lang="ts">
	import { getYearReview, getRecurringPayments, formatEuro, type YearReview, type RecurringPayment } from '$lib/api';
	import { amortizedYearlyCosts } from '$lib/insights';
	import { extractErrorDetail } from '$lib/errors';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import ErrorBanner from '$lib/components/ErrorBanner.svelte';

	let year = $state(new Date().getFullYear());
	let review: YearReview | null = $state(null);
	let recurringPayments: RecurringPayment[] = $state([]);
	let loading = $state(true);
	let error: string | null = $state(null);

	async function load() {
		loading = true;
		error = null;
		try {
			const [reviewResult, payments] = await Promise.all([
				getYearReview(year),
				getRecurringPayments('confirmed')
			]);
			review = reviewResult;
			recurringPayments = payments;
		} catch (e) {
			error = extractErrorDetail(e);
		} finally {
			loading = false;
		}
	}

	$effect(() => { load(); });

	function prevYear() {
		year -= 1;
	}

	function nextYear() {
		year += 1;
	}

	let amortized = $derived(amortizedYearlyCosts(recurringPayments));
</script>

<div class="insights-page">
	<PageHeader title="Insights" />

	{#if error}
		<ErrorBanner message={error} />
	{/if}

	{#if loading}
		<p class="muted">Loading...</p>
	{:else if review}
		<div class="section">
			<div class="year-header">
				<button class="nav-button" onclick={prevYear} aria-label="Previous year">&lt;</button>
				<h2>{review.year}</h2>
				<button class="nav-button" onclick={nextYear} aria-label="Next year">&gt;</button>
			</div>

			<div class="totals-row">
				<div class="total-item">
					<span class="total-label">Income</span>
					<span class="total-value income">{formatEuro(review.income)}</span>
				</div>
				<div class="total-item">
					<span class="total-label">Expenses</span>
					<span class="total-value expenses">{formatEuro(review.expenses)}</span>
				</div>
				<div class="total-item">
					<span class="total-label">Net</span>
					<span class="total-value" class:positive={review.net >= 0} class:negative={review.net < 0}>
						{formatEuro(review.net)}
					</span>
				</div>
			</div>

			{#if review.by_root_category.length === 0}
				<p class="muted">No expense data for {review.year}.</p>
			{:else}
				<table class="year-table">
					<thead>
						<tr>
							<th>Category</th>
							<th class="right">{review.year}</th>
							<th class="right">{review.previous_year.year}</th>
							<th class="right">Delta</th>
						</tr>
					</thead>
					<tbody>
						{#each review.by_root_category as row (row.category_id ?? 'uncategorized')}
							<tr>
								<td>{row.name}</td>
								<td class="right">{formatEuro(row.total)}</td>
								<td class="right">{formatEuro(row.previous_total)}</td>
								<td class="right" class:positive={row.delta <= 0} class:negative={row.delta > 0}>
									{row.delta >= 0 ? '+' : ''}{formatEuro(row.delta)}
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			{/if}
		</div>

		<div class="section">
			<h2>Amortized yearly costs</h2>
			{#if amortized.length === 0}
				<p class="muted">No confirmed yearly recurring payments yet.</p>
			{:else}
				<table class="amortized-table">
					<thead>
						<tr>
							<th>Name</th>
							<th class="right">Per year</th>
							<th class="right">Per month equivalent</th>
						</tr>
					</thead>
					<tbody>
						{#each amortized as item (item.id)}
							<tr>
								<td>{item.name}</td>
								<td class="right">{formatEuro(item.amount)}</td>
								<td class="right">{formatEuro(item.monthly_equivalent)}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			{/if}
		</div>
	{/if}
</div>

<style>
	.insights-page { max-width: 900px; }
	h2 { margin: 0; font-size: 1.1rem; }
	.muted { color: var(--color-text-faint); font-style: italic; }

	.section {
		background: var(--color-card-bg);
		padding: 1.5rem;
		border-radius: var(--radius-md);
		margin-bottom: 1.5rem;
	}

	.year-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		margin-bottom: 1rem;
	}
	.nav-button {
		background: none;
		border: 1px solid var(--color-border);
		border-radius: var(--radius-sm);
		padding: 0.25rem 0.6rem;
		cursor: pointer;
	}
	.nav-button:hover { background: #f5f5f5; }

	.totals-row {
		display: flex;
		gap: 2rem;
		margin-bottom: 1.5rem;
		flex-wrap: wrap;
	}
	.total-item {
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
	}
	.total-label { font-size: 0.8rem; color: var(--color-text-muted); }
	.total-value { font-size: 1.3rem; font-weight: 700; }
	.total-value.income { color: var(--color-income); }
	.total-value.expenses { color: var(--color-expense); }
	.positive { color: var(--color-income) !important; }
	.negative { color: var(--color-expense) !important; }

	table {
		width: 100%;
		border-collapse: collapse;
		font-size: 0.9rem;
	}
	th {
		text-align: left;
		padding: 0.5rem 0;
		border-bottom: 2px solid var(--color-border-light);
		font-size: 0.8rem;
		color: var(--color-text-muted);
	}
	td {
		padding: 0.4rem 0;
		border-bottom: 1px solid var(--color-bg-subtle);
	}
	.right { text-align: right; }
</style>
