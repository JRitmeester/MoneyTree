<script lang="ts">
	import { onMount } from 'svelte';
	import { get } from 'svelte/store';
	import { dateRange, getPayPeriods } from '$lib/stores/dateRange';
	import type { CashflowPeriod } from '$lib/api';

	interface Props {
		dateFrom: string;
		dateTo: string;
		onchange: (dateFrom: string, dateTo: string) => void;
		periods?: { start_date: string; end_date: string }[];
	}

	let { dateFrom = $bindable(), dateTo = $bindable(), onchange, periods = [] }: Props = $props();

	const PRESETS = [
		{ label: '1W', days: 7 },
		{ label: '2W', days: 14 },
		{ label: '1M', months: 1 },
		{ label: '2M', months: 2 },
		{ label: '3M', months: 3 },
		{ label: '6M', months: 6 },
		{ label: '1Y', months: 12 },
	] as const;

	const PERIOD_PRESETS = [1, 2, 3, 6, 12] as const;

	// Pay periods (salary-anchored). getCashflowPeriods returns newest first,
	// so index 0 is the current (open) period.
	const PAY_PERIOD_PRESETS = [
		{ label: 'This', index: 0 },
		{ label: 'Last', index: 1 },
		{ label: '-2', index: 2 },
		{ label: '-3', index: 3 },
	] as const;

	let payPeriods: CashflowPeriod[] = $state([]);

	onMount(async () => {
		try {
			payPeriods = await getPayPeriods();
		} catch {
			payPeriods = [];
		}
	});

	let activePreset: string | null = $state(get(dateRange).activePreset);

	function toISODate(d: Date): string {
		return d.toISOString().split('T')[0];
	}

	function saveToStore() {
		dateRange.set({ activePreset, dateFrom, dateTo });
	}

	function applyPreset(preset: typeof PRESETS[number]) {
		const to = new Date();
		const from = new Date();
		if ('months' in preset) {
			from.setMonth(from.getMonth() - preset.months);
		} else {
			from.setDate(from.getDate() - preset.days);
		}
		dateFrom = toISODate(from);
		dateTo = toISODate(to);
		activePreset = preset.label;
		saveToStore();
		onchange(dateFrom, dateTo);
	}

	function applyPeriodPreset(count: number) {
		if (!periods || periods.length === 0) return;
		// periods are sorted desc by start_date (most recent first)
		const lastIdx = Math.min(count, periods.length) - 1;
		dateFrom = periods[lastIdx].start_date;
		dateTo = periods[0].end_date;
		activePreset = `${count}P`;
		saveToStore();
		onchange(dateFrom, dateTo);
	}

	function applyPayPeriodPreset(index: number) {
		const period = payPeriods[index];
		if (!period) return;
		dateFrom = period.start_date;
		dateTo = period.end_date;
		activePreset = `PP${index}`;
		saveToStore();
		onchange(dateFrom, dateTo);
	}

	function handleDateInput() {
		activePreset = null;
		saveToStore();
		onchange(dateFrom, dateTo);
	}

	// Apply stored date range on mount (falls back to 1M default via store)
	$effect(() => {
		if (!dateFrom && !dateTo) {
			const stored = get(dateRange);
			dateFrom = stored.dateFrom;
			dateTo = stored.dateTo;
		}
	});
</script>

<div class="date-range-filter">
	<div class="presets">
		{#each PRESETS as preset}
			<button
				class="preset-btn"
				class:active={activePreset === preset.label}
				onclick={() => applyPreset(preset)}
			>{preset.label}</button>
		{/each}
	</div>
	{#if periods && periods.length > 0}
		<div class="presets">
			{#each PERIOD_PRESETS as count}
				<button
					class="preset-btn"
					class:active={activePreset === `${count}P`}
					onclick={() => applyPeriodPreset(count)}
					disabled={periods.length === 0}
				>{count}P</button>
			{/each}
		</div>
	{/if}
	{#if payPeriods.length > 0}
		<div class="presets">
			{#each PAY_PERIOD_PRESETS as preset}
				<button
					class="preset-btn"
					class:active={activePreset === `PP${preset.index}`}
					onclick={() => applyPayPeriodPreset(preset.index)}
					disabled={payPeriods.length <= preset.index}
				>{preset.label}</button>
			{/each}
		</div>
	{/if}
	<div class="date-inputs">
		<input type="date" bind:value={dateFrom} onchange={handleDateInput} />
		<span class="separator">-</span>
		<input type="date" bind:value={dateTo} onchange={handleDateInput} />
	</div>
</div>

<style>
	.date-range-filter {
		display: flex;
		align-items: center;
		gap: 0.75rem;
		flex-wrap: wrap;
	}
	.presets {
		display: flex;
		gap: 0;
		border: 1px solid var(--color-border);
		border-radius: var(--radius-sm);
		overflow: hidden;
	}
	.preset-btn {
		padding: 0.4rem 0.6rem;
		background: var(--color-card-bg);
		border: none;
		border-right: 1px solid #eee;
		cursor: pointer;
		font-size: 0.8rem;
		font-weight: 500;
		color: var(--color-text-muted);
		transition: all 0.15s;
	}
	.preset-btn:last-child { border-right: none; }
	.preset-btn:hover:not(:disabled) { background: #f5f5f5; color: var(--color-text); }
	.preset-btn:disabled { opacity: 0.4; cursor: default; }
	.preset-btn.active {
		background: var(--color-accent);
		color: white;
	}
	.date-inputs {
		display: flex;
		align-items: center;
		gap: 0.35rem;
	}
	.date-inputs input {
		padding: 0.4rem 0.5rem;
		border: 1px solid var(--color-border);
		border-radius: var(--radius-sm);
		font-size: 0.85rem;
	}
	.separator { color: var(--color-text-faint); font-size: 0.85rem; }
</style>
