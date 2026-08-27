<script lang="ts">
	import { getBalanceHistory, formatEuro, type BalancePoint } from '$lib/api';
	import { buildBalancePath } from '$lib/balancePath';

	let { dateFrom = '', dateTo = '' }: { dateFrom?: string; dateTo?: string } = $props();

	const WIDTH = 600;
	const HEIGHT = 160;

	let points: BalancePoint[] = $state([]);
	let loading = $state(true);
	let error = $state('');

	$effect(() => {
		const params: { date_from?: string; date_to?: string } = {};
		if (dateFrom) params.date_from = dateFrom;
		if (dateTo) params.date_to = dateTo;
		loading = true;
		error = '';
		getBalanceHistory(params)
			.then((p) => { points = p; })
			.catch((e) => { error = e instanceof Error ? e.message : 'Failed to load balance history'; })
			.finally(() => { loading = false; });
	});

	let chart = $derived(buildBalancePath(points, WIDTH, HEIGHT));
	let last = $derived(points.length > 0 ? points[points.length - 1] : null);
</script>

<div class="section">
	<h2>Checking Balance</h2>
	{#if loading}
		<p class="muted">Loading...</p>
	{:else if error}
		<p class="error">{error}</p>
	{:else if points.length < 2}
		<p class="muted">Not enough data for a balance chart yet.</p>
	{:else}
		<div class="chart-meta">
			<span>Low {formatEuro(chart.min)}</span>
			{#if last}<span class="current">Now {formatEuro(last.balance)}</span>{/if}
			<span>High {formatEuro(chart.max)}</span>
		</div>
		<svg viewBox="0 -8 {WIDTH} {HEIGHT + 16}" preserveAspectRatio="none" role="img"
			aria-label="Checking account balance over time, from {formatEuro(chart.min)} to {formatEuro(chart.max)}">
			<path d={chart.path} fill="none" stroke="#2d6a4f" stroke-width="2" vector-effect="non-scaling-stroke" />
		</svg>
		<div class="chart-dates">
			<span>{points[0].date}</span>
			<span>{last?.date}</span>
		</div>
	{/if}
</div>

<style>
	.section { background: white; padding: 1.5rem; border-radius: 8px; }
	h2 { margin: 0 0 1rem; font-size: 1.1rem; }
	.muted { color: #999; font-style: italic; }
	.error { color: #dc2626; font-size: 0.85rem; }
	svg { width: 100%; height: 160px; display: block; }
	.chart-meta { display: flex; justify-content: space-between; font-size: 0.75rem; color: #666; margin-bottom: 0.35rem; }
	.chart-meta .current { font-weight: 600; color: #2d6a4f; }
	.chart-dates { display: flex; justify-content: space-between; font-size: 0.7rem; color: #999; margin-top: 0.25rem; }
</style>
