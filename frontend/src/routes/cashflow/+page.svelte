<script lang="ts">
	import {
		getCashflowCalendar, getCashflowAdvice, getCashflowSettings, updateCashflowSettings,
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

	let bufferPct = $state(10);
	let bufferSaving = $state(false);

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
			const [calendarResult, adviceResult, settingsResult] = await Promise.all([
				getCashflowCalendar(monthKey(monthDate)),
				getCashflowAdvice(),
				getCashflowSettings()
			]);
			calendar = calendarResult;
			advice = adviceResult;
			bufferPct = settingsResult.buffer_pct;
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

	async function saveBufferPct() {
		bufferSaving = true;
		error = null;
		try {
			const result = await updateCashflowSettings(bufferPct);
			bufferPct = result.buffer_pct;
			advice = await getCashflowAdvice();
		} catch (e) {
			error = extractErrorDetail(e);
		} finally {
			bufferSaving = false;
		}
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
		{#if advice}
			<div class="section advice-card">
				<h2>Payday transfer plan</h2>
				<p class="explainer">
					On payday, move this amount from checking to savings. It covers every
					recurring bill expected before your next salary, plus a safety buffer.
				</p>
				<div class="advice-grid">
					<div class="advice-item">
						<span class="advice-label">Move to savings on {advice.payday ? fmtDate(advice.payday) : ''}</span>
						<span class="advice-value">{formatEuro(advice.sweep_amount ?? 0)}</span>
					</div>
					<div class="advice-item buffer-item">
						<span class="advice-label">Safety buffer</span>
						<span class="buffer-input-row">
							<input
								type="number"
								min="0"
								max="100"
								step="1"
								bind:value={bufferPct}
								onblur={saveBufferPct}
								onkeydown={(e) => { if (e.key === 'Enter') saveBufferPct(); }}
								disabled={bufferSaving}
							/>
							<span>%</span>
						</span>
					</div>
				</div>

				{#if advice.sweep_items.length > 0}
					<details class="calc-details">
						<summary>How this amount is calculated</summary>
						<table class="calc-table">
							<tbody>
								{#each advice.sweep_items as item (item.name + item.date)}
									<tr class:kept={item.kept_in_checking}>
										<td class="calc-date">{fmtDate(item.date)}</td>
										<td class="calc-name">{item.name}</td>
										<td class="calc-amount">
											{#if item.kept_in_checking}
												<span class="kept-note">stays in checking</span>
											{:else}
												{formatEuro(item.amount)}
											{/if}
										</td>
									</tr>
								{/each}
								<tr class="calc-subtotal">
									<td colspan="2">Bills covered from savings</td>
									<td class="calc-amount">{formatEuro(advice.covered_total)}</td>
								</tr>
								<tr>
									<td colspan="2">Safety buffer ({advice.buffer_pct}%)</td>
									<td class="calc-amount">{formatEuro(advice.buffer_amount)}</td>
								</tr>
								<tr class="calc-total">
									<td colspan="2">Total to savings</td>
									<td class="calc-amount">{formatEuro(advice.sweep_amount ?? 0)}</td>
								</tr>
							</tbody>
						</table>
					</details>
				{/if}

				{#if advice.keep_in_checking > 0}
					<p class="keep-in-checking">
						Keep {formatEuro(advice.keep_in_checking)} in checking: those debits hit too
						soon after payday for a transfer back from savings to arrive in time.
					</p>
				{/if}

				{#if advice.standing_buffer > 0}
					<p class="standing-buffer">
						Small 4-weekly payments ({formatEuro(advice.standing_buffer)}) are included
						in the amount above; no separate transfer needed for them.
					</p>
				{/if}

				{#if advice.return_transfers.length > 0}
					<h3>Then move back to checking</h3>
					<p class="explainer">
						These are transfers for you to make yourself, from savings back to
						checking, timed so each bill cluster is funded two business days before
						the money is withdrawn. They are derived from your confirmed recurring
						payments on the Recurring page.
					</p>
					<ul class="transfer-list">
						{#each advice.return_transfers as transfer (transfer.date + transfer.cadence + transfer.covers.join())}
							<li>
								<span class="transfer-date">{fmtDate(transfer.date)}</span>
								<span class="transfer-amount">{formatEuro(transfer.amount)}</span>
								<span class="transfer-covers">for {transfer.covers.join(', ')}</span>
							</li>
						{/each}
					</ul>
				{/if}

				{#if advice.warnings.length > 0}
					<div class="warning-box">
						<h3>Heads up</h3>
						<ul class="warning-list">
							{#each advice.warnings as warning (warning)}
								<li>{warning}</li>
							{/each}
						</ul>
					</div>
				{/if}
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

	.advice-grid {
		display: flex;
		gap: 2rem;
		flex-wrap: wrap;
	}
	.advice-item {
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
	}
	.advice-label { font-size: 0.8rem; color: var(--color-text-muted); }
	.advice-value { font-size: 1.4rem; font-weight: 700; color: var(--color-text); }
	.buffer-input-row {
		display: flex;
		align-items: center;
		gap: 0.35rem;
	}
	.buffer-input-row input {
		width: 4.5rem;
		padding: 0.3rem 0.5rem;
		border: 1px solid var(--color-border);
		border-radius: 4px;
		font-size: 1rem;
	}

	.explainer {
		font-size: 0.85rem;
		color: var(--color-text-muted);
		margin: 0 0 1rem;
		max-width: 46rem;
	}
	h3 + .explainer { margin-top: 0.25rem; }

	.calc-details {
		margin-top: 1rem;
		font-size: 0.85rem;
	}
	.calc-details summary {
		cursor: pointer;
		color: var(--color-accent);
		font-weight: 600;
		user-select: none;
	}
	.calc-table {
		margin-top: 0.75rem;
		border-collapse: collapse;
		min-width: 22rem;
	}
	.calc-table td {
		padding: 0.25rem 0.75rem 0.25rem 0;
		border-bottom: 1px solid #f0f0f0;
	}
	.calc-date { color: var(--color-text-muted); white-space: nowrap; }
	.calc-amount { text-align: right; white-space: nowrap; }
	.calc-table tr.kept .calc-name { color: var(--color-text-muted); }
	.kept-note { color: var(--color-text-faint); font-style: italic; }
	.calc-subtotal td { border-top: 2px solid var(--color-border); font-weight: 600; }
	.calc-total td { font-weight: 700; border-bottom: none; }

	.transfer-list, .warning-list {
		list-style: none;
		padding: 0;
		margin: 0;
		display: flex;
		flex-direction: column;
		gap: 0.4rem;
	}
	.transfer-list li {
		display: flex;
		gap: 0.75rem;
		align-items: baseline;
		font-size: 0.9rem;
	}
	.transfer-date { font-weight: 600; }
	.transfer-amount { color: var(--color-text); }
	.transfer-covers { color: var(--color-text-muted); font-size: 0.85rem; }
	.keep-in-checking, .standing-buffer {
		font-size: 0.85rem;
		color: #444;
		margin: 0.5rem 0 0;
	}
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
		.buffer-input-row input {
			min-height: 44px;
		}
		.nav-button {
			min-width: 44px;
			min-height: 44px;
		}
	}
</style>
