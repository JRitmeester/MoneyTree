<script lang="ts">
	interface Props {
		dateFrom: string;
		dateTo: string;
		onchange: (dateFrom: string, dateTo: string) => void;
	}

	let { dateFrom = $bindable(), dateTo = $bindable(), onchange }: Props = $props();

	const PRESETS = [
		{ label: '1W', days: 7 },
		{ label: '2W', days: 14 },
		{ label: '1M', months: 1 },
		{ label: '2M', months: 2 },
		{ label: '3M', months: 3 },
		{ label: '6M', months: 6 },
		{ label: '1Y', months: 12 },
	] as const;

	let activePreset: string | null = $state('1M');

	function toISODate(d: Date): string {
		return d.toISOString().split('T')[0];
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
		onchange(dateFrom, dateTo);
	}

	function handleDateInput() {
		activePreset = null;
		onchange(dateFrom, dateTo);
	}

	// Apply default 1M preset on mount
	$effect(() => {
		if (!dateFrom && !dateTo) {
			const to = new Date();
			const from = new Date();
			from.setMonth(from.getMonth() - 1);
			dateFrom = toISODate(from);
			dateTo = toISODate(to);
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
		border: 1px solid #ddd;
		border-radius: 6px;
		overflow: hidden;
	}
	.preset-btn {
		padding: 0.4rem 0.6rem;
		background: white;
		border: none;
		border-right: 1px solid #eee;
		cursor: pointer;
		font-size: 0.8rem;
		font-weight: 500;
		color: #666;
		transition: all 0.15s;
	}
	.preset-btn:last-child { border-right: none; }
	.preset-btn:hover { background: #f5f5f5; color: #1a1a1a; }
	.preset-btn.active {
		background: #2d6a4f;
		color: white;
	}
	.date-inputs {
		display: flex;
		align-items: center;
		gap: 0.35rem;
	}
	.date-inputs input {
		padding: 0.4rem 0.5rem;
		border: 1px solid #ddd;
		border-radius: 6px;
		font-size: 0.85rem;
	}
	.separator { color: #999; font-size: 0.85rem; }
</style>
