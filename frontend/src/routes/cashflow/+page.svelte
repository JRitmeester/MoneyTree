<script lang="ts">
	import {
		getCashflowCalendar, getCashflowAdvice, getCashflowSettings, updateCashflowSettings,
		formatEuro,
		type CashflowCalendar, type CashflowAdvice
	} from '$lib/api';
	import { extractErrorDetail } from '$lib/errors';

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
	<div class="header">
		<h1>Cash flow</h1>
	</div>

	{#if error}
		<div class="error">{error}</div>
	{/if}

	{#if loading}
		<p class="muted">Loading...</p>
	{:else if advice && !advice.salary_confirmed}
		<div class="section empty-state">
			<p>{advice.message}.</p>
			<a href="/recurring" class="confirm-link">Go to Recurring</a>
		</div>
	{:else}
		{#if advice}
			<div class="section advice-card">
				<h2>Transfer advice</h2>
				<div class="advice-grid">
					<div class="advice-item">
						<span class="advice-label">Sweep on payday ({advice.payday})</span>
						<span class="advice-value">{formatEuro(advice.sweep_amount ?? 0)}</span>
					</div>
					<div class="advice-item buffer-item">
						<span class="advice-label">Buffer</span>
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

				{#if advice.return_transfers.length > 0}
					<h3>Return transfers</h3>
					<ul class="transfer-list">
						{#each advice.return_transfers as transfer}
							<li>
								<span class="transfer-date">{transfer.date}</span>
								<span class="transfer-amount">{formatEuro(transfer.amount)}</span>
								<span class="transfer-covers">for {transfer.covers.join(', ')}</span>
							</li>
						{/each}
					</ul>
				{/if}

				{#if advice.warnings.length > 0}
					<h3>Warnings</h3>
					<ul class="warning-list">
						{#each advice.warnings as warning}
							<li>{warning}</li>
						{/each}
					</ul>
				{/if}
			</div>
		{/if}

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
									<div class="day-item" class:income={item.is_income}>
										{item.name} {formatEuro(item.amount)}
									</div>
								{/each}
							{/if}
						</div>
					{/each}
				</div>
			{/each}
		</div>
	{/if}
</div>

<style>
	.cashflow-page { max-width: 1000px; }
	.header { margin-bottom: 1.5rem; }
	h1 { margin: 0; color: #1a1a1a; }
	h2 { margin: 0 0 1rem; font-size: 1.1rem; }
	h3 { margin: 1rem 0 0.5rem; font-size: 0.95rem; }
	.muted { color: #999; font-style: italic; }
	.error {
		background: #fef2f2;
		color: #b91c1c;
		padding: 0.75rem 1rem;
		border-radius: 6px;
		margin-bottom: 1rem;
	}

	.section {
		background: white;
		padding: 1.5rem;
		border-radius: 8px;
		margin-bottom: 1.5rem;
	}

	.empty-state {
		text-align: center;
		padding: 2rem;
		color: #666;
	}
	.confirm-link {
		display: inline-block;
		margin-top: 0.5rem;
		color: #2d6a4f;
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
	.advice-label { font-size: 0.8rem; color: #666; }
	.advice-value { font-size: 1.4rem; font-weight: 700; color: #1a1a1a; }
	.buffer-input-row {
		display: flex;
		align-items: center;
		gap: 0.35rem;
	}
	.buffer-input-row input {
		width: 4.5rem;
		padding: 0.3rem 0.5rem;
		border: 1px solid #ddd;
		border-radius: 4px;
		font-size: 1rem;
	}

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
	.transfer-amount { color: #1a1a1a; }
	.transfer-covers { color: #666; font-size: 0.85rem; }
	.warning-list li {
		font-size: 0.85rem;
		color: #a16207;
	}

	.calendar-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
	}
	.calendar-header h2 { margin: 0; }
	.nav-button {
		background: none;
		border: 1px solid #ddd;
		border-radius: 6px;
		padding: 0.25rem 0.6rem;
		cursor: pointer;
	}
	.nav-button:hover { background: #f5f5f5; }

	.weekday-row, .week-row {
		display: grid;
		grid-template-columns: repeat(7, 1fr);
		gap: 0.35rem;
	}
	.weekday-row { margin: 1rem 0 0.35rem; }
	.weekday-label {
		font-size: 0.75rem;
		color: #999;
		text-align: center;
	}
	.week-row { margin-bottom: 0.35rem; }
	.day-cell {
		min-height: 4.5rem;
		border: 1px solid #eee;
		border-radius: 6px;
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
</style>
