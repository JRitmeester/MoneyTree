<script lang="ts">
	import {
		getCashflowCalendar, getCashflowAdvice,
		formatEuro,
		type CashflowCalendar, type CashflowAdvice
	} from '$lib/api';
	import { extractErrorDetail } from '$lib/errors';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import SalaryAllocationCard from '$lib/components/SalaryAllocationCard.svelte';
	import ErrorBanner from '$lib/components/ErrorBanner.svelte';
	import Loading from '$lib/components/Loading.svelte';

	let monthDate = $state(startOfMonth(new Date()));
	let calendar: CashflowCalendar | null = $state(null);
	let advice: CashflowAdvice | null = $state(null);
	let loading = $state(true);
	let error: string | null = $state(null);

	function startOfMonth(d: Date): Date {
		return new Date(d.getFullYear(), d.getMonth(), 1);
	}

	function monthKey(d: Date): string {
		const year = d.getFullYear();
		const month = String(d.getMonth() + 1).padStart(2, '0');
		return `${year}-${month}`;
	}

	function monthLabel(d: Date): string {
		return d.toLocaleDateString('en-GB', { month: 'long', year: 'numeric' });
	}

	function fmtDate(iso: string): string {
		return new Date(iso).toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' });
	}

	async function load() {
		loading = true;
		error = null;
		try {
			const [calendarResult, adviceResult] = await Promise.all([
				getCashflowCalendar(monthKey(monthDate)),
				getCashflowAdvice()
			]);
			calendar = calendarResult;
			advice = adviceResult;
		} catch (e) {
			error = extractErrorDetail(e);
		} finally {
			loading = false;
		}
	}

	$effect(() => { load(); });

	function prevMonth() {
		monthDate = new Date(monthDate.getFullYear(), monthDate.getMonth() - 1, 1);
	}

	function nextMonth() {
		monthDate = new Date(monthDate.getFullYear(), monthDate.getMonth() + 1, 1);
	}

	// Build a 7-column week grid for the current month, padded with leading
	// blanks so the 1st lands under the correct weekday (Monday-first).
	let weeks = $derived.by(() => {
		if (!calendar) return [];
		const year = monthDate.getFullYear();
		const month = monthDate.getMonth();
		const daysInMonth = new Date(year, month + 1, 0).getDate();
		const firstWeekday = (new Date(year, month, 1).getDay() + 6) % 7; // Monday = 0

		const itemsByDate = new Map(calendar.days.map((d) => [d.date, d.items]));
		const cells: { date: string | null; day: number | null }[] = [];
		for (let i = 0; i < firstWeekday; i++) cells.push({ date: null, day: null });
		for (let day = 1; day <= daysInMonth; day++) {
			const dateStr = `${year}-${String(month + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
			cells.push({ date: dateStr, day });
		}
		while (cells.length % 7 !== 0) cells.push({ date: null, day: null });

		const result = [];
		for (let i = 0; i < cells.length; i += 7) {
			result.push(cells.slice(i, i + 7).map((c) => ({
				...c,
				items: c.date ? (itemsByDate.get(c.date) ?? []) : []
			})));
		}
		return result;
	});
</script>

<div class="cashflow-page">
	<PageHeader title="Cash flow" />

	{#if error}
		<ErrorBanner message={error} />
	{/if}

	{#if loading}
		<Loading />
	{:else if advice && !advice.salary_confirmed}
		<div class="section empty-state">
			<p>{advice.message}.</p>
			<a href="/recurring" class="confirm-link">Go to Recurring</a>
		</div>
	{:else}
		{#if advice && (advice.yearly_due.length > 0 || advice.warnings.length > 0)}
			<div class="section">
				<div class="warning-box">
					<h3>Heads up</h3>
					{#if advice.yearly_due.length > 0}
						<p class="warning-intro">Yearly payments due within 30 days:</p>
						<table class="mini-table">
							<tbody>
								{#each advice.yearly_due as item (item.name + item.date)}
									<tr>
										<td>{item.name}</td>
										<td class="nowrap">{fmtDate(item.date)}</td>
									</tr>
								{/each}
							</tbody>
						</table>
					{/if}
					{#if advice.warnings.length > 0}
						<ul class="warning-list">
							{#each advice.warnings as warning (warning)}
								<li>{warning}</li>
							{/each}
						</ul>
					{/if}
				</div>
			</div>
		{/if}

		<SalaryAllocationCard />

		<div class="section">
			<div class="calendar-header">
				<button class="nav-button" onclick={prevMonth} aria-label="Previous month">&lt;</button>
				<h2>{monthLabel(monthDate)}</h2>
				<button class="nav-button" onclick={nextMonth} aria-label="Next month">&gt;</button>
			</div>
			<div class="weekday-row">
				{#each ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'] as label}
					<div class="weekday-label">{label}</div>
				{/each}
			</div>
			{#each weeks as week}
				<div class="week-row">
					{#each week as cell}
						<div class="day-cell" class:empty={!cell.day} class:salary-day={cell.items.some((i) => i.is_salary)}>
							{#if cell.day}
								<div class="day-number">{cell.day}</div>
								{#each cell.items as item}
									<div
										class="day-item"
										class:income={item.is_income}
										title="{item.name} {formatEuro(item.amount)}"
									>
										{item.name} {formatEuro(item.amount)}
									</div>
								{/each}
							{/if}
						</div>
					{/each}
				</div>
			{/each}

			<!-- Mobile: the 7-column grid becomes a vertical agenda list of days
			     that actually have items. Toggled purely via media query. -->
			<div class="agenda-list">
				{#if calendar && calendar.days.some((d) => d.items.length > 0)}
					{#each calendar.days.filter((d) => d.items.length > 0) as day (day.date)}
						<div class="agenda-day" class:salary-day={day.items.some((i) => i.is_salary)}>
							<div class="agenda-date">
								{new Date(day.date).toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric' })}
							</div>
							<div class="agenda-items">
								{#each day.items as item}
									<div class="day-item" class:income={item.is_income}>
										{item.name} {formatEuro(item.amount)}
									</div>
								{/each}
							</div>
						</div>
					{/each}
				{:else}
					<p class="muted">No cash flow items this month.</p>
				{/if}
			</div>
		</div>
	{/if}
</div>

<style>
	.cashflow-page { max-width: 1000px; }
	h2 { margin: 0 0 1rem; font-size: 1.1rem; }
	h3 { margin: 1rem 0 0.5rem; font-size: 0.95rem; }
	
	.section {
		background: var(--color-card-bg);
		padding: 1.5rem;
		border-radius: var(--radius-md);
		margin-bottom: 1.5rem;
	}

	.empty-state {
		text-align: center;
		padding: 2rem;
		color: var(--color-text-muted);
	}
	.confirm-link {
		display: inline-block;
		margin-top: 0.5rem;
		color: var(--color-accent);
		font-weight: 600;
	}




	.warning-list {
		list-style: none;
		padding: 0;
		margin: 0;
		display: flex;
		flex-direction: column;
		gap: 0.4rem;
	}
	.mini-table {
		border-collapse: collapse;
		font-size: 0.85rem;
		margin-top: 0.25rem;
	}
	.mini-table td {
		padding: 0.3rem 1.25rem 0.3rem 0;
		border-bottom: 1px solid #f0f0f0;
		vertical-align: baseline;
	}
	.mini-table tr:last-child td { border-bottom: none; }
	.mini-table .nowrap { white-space: nowrap; }
	.warning-intro {
		font-size: 0.85rem;
		margin: 0.5rem 0 0.25rem;
	}
	.warning-box .mini-table td { border-bottom-color: #fde68a; }
	.warning-box {
		margin-top: 1.25rem;
		background: var(--color-warn-bg-amber);
		border: 1px solid #facc15;
		border-left: 4px solid var(--color-amber);
		border-radius: var(--radius-sm);
		padding: 0.75rem 1rem;
	}
	.warning-box h3 {
		margin: 0 0 0.5rem;
		color: var(--color-amber);
	}
	.warning-list li {
		font-size: 0.85rem;
		color: var(--color-text);
		line-height: 1.4;
	}
	.warning-list li + li {
		margin-top: 0.25rem;
		padding-top: 0.25rem;
		border-top: 1px solid #fde68a;
	}

	.calendar-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
	}
	.calendar-header h2 { margin: 0; }
	.nav-button {
		background: none;
		border: 1px solid var(--color-border);
		border-radius: var(--radius-sm);
		padding: 0.25rem 0.6rem;
		cursor: pointer;
	}
	.nav-button:hover { background: #f5f5f5; }

	.weekday-row, .week-row {
		display: grid;
		/* minmax(0, 1fr) keeps all seven columns exactly equal: long item
		   names truncate inside their cell instead of widening the column. */
		grid-template-columns: repeat(7, minmax(0, 1fr));
		gap: 0.35rem;
	}
	.weekday-row { margin: 1rem 0 0.35rem; }
	.weekday-label {
		font-size: 0.75rem;
		color: var(--color-text-faint);
		text-align: center;
	}
	.week-row { margin-bottom: 0.35rem; }
	.day-cell {
		min-height: 4.5rem;
		min-width: 0;
		overflow: hidden;
		border: 1px solid #eee;
		border-radius: var(--radius-sm);
		padding: 0.35rem;
		font-size: 0.75rem;
	}
	.day-cell.empty { border-color: transparent; }
	.day-cell.salary-day {
		background: #dcfce7;
		border-color: #86efac;
	}
	.day-number {
		font-weight: 600;
		color: #444;
		margin-bottom: 0.2rem;
	}
	.day-item {
		color: #b91c1c;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.day-item.income {
		color: #15803d;
	}

	.agenda-list {
		display: none;
	}
	.muted {
		color: var(--color-text-muted);
	}

	@media (max-width: 480px) {
		/* Swap the 7-column week grid for a vertical agenda list; much easier
		   to read and tap on a narrow screen. */
		.weekday-row,
		.week-row {
			display: none;
		}
		.agenda-list {
			display: flex;
			flex-direction: column;
			gap: 0.5rem;
			margin-top: 1rem;
		}
		.agenda-day {
			border: 1px solid #eee;
			border-radius: var(--radius-sm);
			padding: 0.6rem 0.75rem;
		}
		.agenda-day.salary-day {
			background: #dcfce7;
			border-color: #86efac;
		}
		.agenda-date {
			font-weight: 600;
			color: #444;
			font-size: 0.85rem;
			margin-bottom: 0.25rem;
		}
		.agenda-items {
			display: flex;
			flex-direction: column;
			gap: 0.15rem;
			font-size: 0.85rem;
		}
			.nav-button {
			min-width: 44px;
			min-height: 44px;
		}
	}
</style>
