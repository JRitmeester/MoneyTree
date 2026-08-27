<script lang="ts">
	import { getIncidentalLabels, getSavingsCapacity, formatEuro, type IncidentalLabelSummary, type SavingsCapacitySummary } from '$lib/api';

	let data = $state<SavingsCapacitySummary | null>(null);
	let labelSummaries: IncidentalLabelSummary[] = $state([]);
	let loading = $state(true);
	let error = $state('');

	$effect(() => {
		loading = true;
		error = '';
		getSavingsCapacity(6)
			.then((d) => { data = d; })
			.catch((e) => { error = e instanceof Error ? e.message : 'Failed to load savings capacity'; })
			.finally(() => { loading = false; });
		getIncidentalLabels()
			.then((ls) => { labelSummaries = ls.filter((l) => l.count > 0); })
			.catch(() => { labelSummaries = []; });
	});

	let headline = $derived(data?.trailing_6_structural ?? data?.trailing_3_structural ?? null);
	let headlineWindow = $derived(data?.trailing_6_structural != null ? 6 : 3);
</script>

<div class="section">
	<h2>Savings Capacity</h2>
	{#if loading}
		<p class="muted">Loading...</p>
	{:else if error}
		<p class="error">{error}</p>
	{:else if !data || data.months.length === 0}
		<p class="muted">No data yet. Import transactions first.</p>
	{:else}
		{#if headline != null}
			<div class="headline" class:positive={headline >= 0} class:negative={headline < 0}>
				<span class="headline-value">{formatEuro(headline)}</span>
				<span class="headline-label">structural savings capacity per month ({headlineWindow}-month average)</span>
			</div>
		{:else}
			<p class="muted">
				Fewer than 3 complete months of data; showing months without an average.
			</p>
		{/if}

		<div class="capacity-table">
			<div class="row head">
				<span>Month</span>
				<span class="right">Income</span>
				<span class="right">Structural</span>
				<span class="right">Incidental</span>
				<span class="right">Net</span>
			</div>
			{#each data.months as m (m.month)}
				<div class="row" class:partial={m.partial}>
					<span>{m.month}{m.partial ? ' *' : ''}</span>
					<span class="right income-text">{formatEuro(m.income)}</span>
					<span class="right expense-text">{formatEuro(m.expenses_structural)}</span>
					<span class="right incidental-text">{formatEuro(m.incidental)}</span>
					<span class="right" class:positive={m.net_structural >= 0} class:negative={m.net_structural < 0}>
						{formatEuro(m.net_structural)}
					</span>
				</div>
			{/each}
		</div>
		{#if data.months.some((m) => m.partial)}
			<p class="footnote">* partial month, excluded from averages</p>
		{/if}
		{#if data.trailing_3_structural != null}
			<p class="footnote">
				3-month average {formatEuro(data.trailing_3_structural)} structural
				({formatEuro(data.trailing_3_raw ?? 0)} including incidentals)
			</p>
		{/if}
		{#if labelSummaries.length > 0}
			<div class="labels">
				<h3>Incidental by label</h3>
				{#each labelSummaries as label (label.id)}
					<div class="label-row">
						<span class="label-name">{label.name}</span>
						<span class="label-range">{label.date_from} to {label.date_to}</span>
						<span class="label-total">{formatEuro(label.total)}</span>
					</div>
				{/each}
			</div>
		{/if}
	{/if}
</div>

<style>
	.section { background: white; padding: 1.5rem; border-radius: 8px; }
	h2 { margin: 0 0 1rem; font-size: 1.1rem; }
	.muted { color: #999; font-style: italic; }
	.error { color: #dc2626; font-size: 0.85rem; }
	.headline { margin-bottom: 1rem; }
	.headline-value { font-size: 1.6rem; font-weight: 700; }
	.headline-label { display: block; font-size: 0.8rem; color: #666; }
	.positive { color: #16a34a; }
	.negative { color: #dc2626; }
	.capacity-table { font-size: 0.85rem; }
	.row { display: grid; grid-template-columns: 1.2fr 1fr 1fr 1fr 1fr; padding: 0.35rem 0; border-bottom: 1px solid #f0f0f0; }
	.row.head { font-weight: 600; font-size: 0.75rem; color: #666; border-bottom: 2px solid #e5e7eb; }
	.row.partial { color: #999; }
	.right { text-align: right; }
	.income-text { color: #16a34a; }
	.expense-text { color: #dc2626; }
	.incidental-text { color: #a16207; }
	.footnote { font-size: 0.7rem; color: #999; margin: 0.4rem 0 0; }
	.labels { margin-top: 1rem; border-top: 1px solid #f0f0f0; padding-top: 0.75rem; }
	h3 { font-size: 0.85rem; margin: 0 0 0.5rem; color: #666; }
	.label-row { display: flex; justify-content: space-between; gap: 0.75rem; font-size: 0.85rem; padding: 0.2rem 0; }
	.label-name { font-weight: 500; }
	.label-range { color: #999; font-size: 0.75rem; flex: 1; text-align: right; }
	.label-total { font-weight: 600; color: #a16207; }
</style>
