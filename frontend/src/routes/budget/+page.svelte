<script lang="ts">
	import { goto } from '$app/navigation';
	import {
		getBudgetVsActual, getBudget, createBudget, updateBudget, copyBudget, deleteBudget,
		getBudgets, getCategories,
		formatEuro,
		type BudgetVsActualSummary, type BudgetVsActualLine, type Budget, type BudgetSummary, type Category
	} from '$lib/api';

	const MONTH_NAMES = [
		'January', 'February', 'March', 'April', 'May', 'June',
		'July', 'August', 'September', 'October', 'November', 'December'
	];

	let now = new Date();
	let currentYear = $state(now.getFullYear());
	let currentMonth = $state(now.getMonth() + 1);

	let data: BudgetVsActualSummary | null = $state(null);
	let budget: Budget | null = $state(null);
	let allBudgets: BudgetSummary[] = $state([]);
	let categories: Category[] = $state([]);
	let loading = $state(true);
	let error: string | null = $state(null);
	let editing = $state(false);

	// Edit state: category_id -> amount
	let editLines: { category_id: number; category_name: string; category_type: string; amount: number }[] = $state([]);

	let monthLabel = $derived(`${MONTH_NAMES[currentMonth - 1]} ${currentYear}`);

	// Find the nearest previous budget for "copy from" functionality
	let nearestPreviousBudget = $derived.by(() => {
		for (const b of allBudgets) {
			if (b.year < currentYear || (b.year === currentYear && b.month < currentMonth)) {
				return b;
			}
		}
		return null;
	});

	function flatCategories(cats: Category[], depth = 0): { id: number; name: string; category_type: string; depth: number }[] {
		let result: { id: number; name: string; category_type: string; depth: number }[] = [];
		for (const c of cats) {
			result.push({ id: c.id, name: c.name, category_type: c.category_type, depth });
			if (c.children?.length) {
				result = result.concat(flatCategories(c.children, depth + 1));
			}
		}
		return result;
	}

	async function load() {
		loading = true;
		error = null;
		try {
			const [bva, budgets, cats] = await Promise.all([
				getBudgetVsActual(currentYear, currentMonth),
				getBudgets(),
				getCategories(),
			]);
			data = bva;
			allBudgets = budgets;
			categories = cats;

			try {
				budget = await getBudget(currentYear, currentMonth);
			} catch {
				budget = null;
			}
		} catch (e: any) {
			error = e.message;
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		// Re-load when month changes
		currentYear; currentMonth;
		load();
	});

	function prevMonth() {
		if (currentMonth === 1) {
			currentMonth = 12;
			currentYear--;
		} else {
			currentMonth--;
		}
	}

	function nextMonth() {
		if (currentMonth === 12) {
			currentMonth = 1;
			currentYear++;
		} else {
			currentMonth++;
		}
	}

	async function handleCreateBudget() {
		try {
			await createBudget({ year: currentYear, month: currentMonth, lines: [] });
			await load();
			startEditing();
		} catch (e: any) {
			error = e.message;
		}
	}

	async function handleCopyBudget() {
		if (!nearestPreviousBudget) return;
		try {
			await copyBudget(currentYear, currentMonth, nearestPreviousBudget.year, nearestPreviousBudget.month);
			await load();
		} catch (e: any) {
			error = e.message;
		}
	}

	async function handleDeleteBudget() {
		if (!confirm('Delete this budget?')) return;
		try {
			await deleteBudget(currentYear, currentMonth);
			budget = null;
			await load();
		} catch (e: any) {
			error = e.message;
		}
	}

	function startEditing() {
		const flat = flatCategories(categories);
		// Pre-fill from existing budget lines
		const budgetMap = new Map<number, number>();
		if (budget) {
			for (const line of budget.lines) {
				budgetMap.set(line.category_id, line.amount);
			}
		}

		editLines = flat
			.filter(c => !categories.find(root => root.children?.some(ch => ch.id === c.id) && c.depth === 0))
			.map(c => ({
				category_id: c.id,
				category_name: c.name,
				category_type: c.category_type,
				amount: budgetMap.get(c.id) ?? 0,
			}));

		editing = true;
	}

	async function saveEditing() {
		const lines = editLines
			.filter(l => l.amount > 0)
			.map(l => ({ category_id: l.category_id, amount: l.amount }));

		try {
			if (budget) {
				await updateBudget(currentYear, currentMonth, { lines });
			} else {
				await createBudget({ year: currentYear, month: currentMonth, lines });
			}
			editing = false;
			await load();
		} catch (e: any) {
			error = e.message;
		}
	}

	function cancelEditing() {
		editing = false;
	}

	function progressWidth(line: BudgetVsActualLine): string {
		if (line.budgeted === 0) return '100%';
		return `${Math.min(line.percentage, 100)}%`;
	}

	function isOverBudget(line: BudgetVsActualLine): boolean {
		if (line.category_type === 'income') return false;
		return line.actual > line.budgeted && line.budgeted > 0;
	}

	function formatDiff(line: BudgetVsActualLine): string {
		if (line.category_type === 'income') {
			if (line.difference >= 0) return `+${formatEuro(line.difference)}`;
			return formatEuro(line.difference);
		}
		// Expense: difference = budgeted - actual
		if (line.difference >= 0) return `${formatEuro(line.difference)} left`;
		return `${formatEuro(Math.abs(line.difference))} over`;
	}
</script>

<div class="budget-page">
	<div class="header">
		<div class="month-selector">
			<button class="nav-btn" onclick={prevMonth}>&larr;</button>
			<h1>{monthLabel}</h1>
			<button class="nav-btn" onclick={nextMonth}>&rarr;</button>
		</div>
		<div class="actions">
			{#if budget && !editing}
				<button class="btn primary" onclick={startEditing}>Edit Budget</button>
				<button class="btn danger-outline" onclick={handleDeleteBudget}>Delete</button>
			{/if}
			{#if editing}
				<button class="btn primary" onclick={saveEditing}>Save</button>
				<button class="btn secondary" onclick={cancelEditing}>Cancel</button>
			{/if}
		</div>
	</div>

	{#if loading}
		<div class="loading">Loading...</div>
	{:else if error}
		<div class="error">{error}</div>
	{:else if editing}
		<!-- EDIT MODE -->
		<div class="edit-section">
			<div class="section">
				<h2>Income Categories</h2>
				<div class="edit-table">
					<div class="edit-header">
						<span>Category</span>
						<span class="right">Monthly Budget</span>
					</div>
					{#each editLines.filter(l => l.category_type === 'income') as line}
						<div class="edit-row">
							<span>{line.category_name}</span>
							<input type="number" step="0.01" min="0" bind:value={line.amount} />
						</div>
					{/each}
					{#if editLines.filter(l => l.category_type === 'income').length === 0}
						<p class="muted">No income categories. Create them on the <a href="/categories">Categories page</a>.</p>
					{/if}
				</div>
			</div>
			<div class="section">
				<h2>Expense Categories</h2>
				<div class="edit-table">
					<div class="edit-header">
						<span>Category</span>
						<span class="right">Monthly Budget</span>
					</div>
					{#each editLines.filter(l => l.category_type === 'expense') as line}
						<div class="edit-row">
							<span>{line.category_name}</span>
							<input type="number" step="0.01" min="0" bind:value={line.amount} />
						</div>
					{/each}
					{#if editLines.filter(l => l.category_type === 'expense').length === 0}
						<p class="muted">No expense categories. Create them on the <a href="/categories">Categories page</a>.</p>
					{/if}
				</div>
			</div>
		</div>
	{:else if !budget}
		<!-- NO BUDGET -->
		<div class="no-budget">
			<p>No budget set for {monthLabel}.</p>
			<div class="no-budget-actions">
				<button class="btn primary" onclick={handleCreateBudget}>Create Budget</button>
				{#if nearestPreviousBudget}
					<button class="btn secondary" onclick={handleCopyBudget}>
						Copy from {MONTH_NAMES[nearestPreviousBudget.month - 1]} {nearestPreviousBudget.year}
					</button>
				{/if}
			</div>

			{#if data && (data.total_actual_income > 0 || data.total_actual_expenses > 0)}
				<div class="actuals-preview">
					<p class="muted">You have transactions this month but no budget to compare against:</p>
					<div class="summary-cards">
						<div class="card income">
							<div class="card-value">{formatEuro(data.total_actual_income)}</div>
							<div class="card-label">Actual Income</div>
						</div>
						<div class="card expenses">
							<div class="card-value">{formatEuro(data.total_actual_expenses)}</div>
							<div class="card-label">Actual Expenses</div>
						</div>
						<div class="card net" class:positive={data.actual_net >= 0} class:negative={data.actual_net < 0}>
							<div class="card-value">{formatEuro(data.actual_net)}</div>
							<div class="card-label">Net</div>
						</div>
					</div>
				</div>
			{/if}
		</div>
	{:else if data}
		<!-- BUDGET VS ACTUAL VIEW -->
		<div class="summary-cards">
			<div class="card">
				<div class="card-value income-text">{formatEuro(data.total_budgeted_income)}</div>
				<div class="card-label">Budgeted Income</div>
			</div>
			<div class="card">
				<div class="card-value income-text">{formatEuro(data.total_actual_income)}</div>
				<div class="card-label">Actual Income</div>
			</div>
			<div class="card">
				<div class="card-value expense-text">{formatEuro(data.total_budgeted_expenses)}</div>
				<div class="card-label">Budgeted Expenses</div>
			</div>
			<div class="card">
				<div class="card-value expense-text">{formatEuro(data.total_actual_expenses)}</div>
				<div class="card-label">Actual Expenses</div>
			</div>
			<div class="card" class:positive={data.actual_net >= 0} class:negative={data.actual_net < 0}>
				<div class="card-value">{formatEuro(data.actual_net)}</div>
				<div class="card-label">Net</div>
			</div>
			<div class="card">
				<div class="card-value" style="color: #2d6a4f">{data.savings_rate.toFixed(1)}%</div>
				<div class="card-label">Savings Rate</div>
			</div>
		</div>

		{#if data.income_lines.length > 0}
			<div class="section">
				<h2>Income</h2>
				<div class="bva-table">
					<div class="bva-header">
						<span>Category</span>
						<span class="right">Budgeted</span>
						<span class="right">Actual</span>
						<span class="right">Difference</span>
						<span class="bar-col">Progress</span>
					</div>
					{#each data.income_lines as line}
						<div class="bva-row">
							<span class="cat-name">{line.category_name}</span>
							<span class="right">{formatEuro(line.budgeted)}</span>
							<span class="right">{formatEuro(line.actual)}</span>
							<span class="right" class:positive={line.difference >= 0} class:negative={line.difference < 0}>
								{formatDiff(line)}
							</span>
							<span class="bar-col">
								<div class="bar-bg">
									<div
										class="bar-fill income-bar"
										style="width: {progressWidth(line)}"
									></div>
								</div>
							</span>
						</div>
					{/each}
				</div>
			</div>
		{/if}

		{#if data.expense_lines.length > 0}
			<div class="section">
				<h2>Expenses</h2>
				<div class="bva-table">
					<div class="bva-header">
						<span>Category</span>
						<span class="right">Budgeted</span>
						<span class="right">Actual</span>
						<span class="right">Remaining</span>
						<span class="bar-col">Progress</span>
					</div>
					{#each data.expense_lines as line}
						<div class="bva-row" class:over-budget={isOverBudget(line)}>
							<span class="cat-name">{line.category_name}</span>
							<span class="right">{formatEuro(line.budgeted)}</span>
							<span class="right">{formatEuro(line.actual)}</span>
							<span class="right" class:positive={line.difference >= 0} class:negative={line.difference < 0}>
								{formatDiff(line)}
							</span>
							<span class="bar-col">
								<div class="bar-bg">
									<div
										class="bar-fill"
										class:expense-bar-ok={!isOverBudget(line)}
										class:expense-bar-over={isOverBudget(line)}
										style="width: {progressWidth(line)}"
									></div>
								</div>
							</span>
						</div>
					{/each}
				</div>
			</div>
		{/if}

		{#if data.unmapped_expenses > 0 || data.unmapped_income > 0}
			<div class="unmapped-warning">
				<strong>Unmapped transactions</strong>
				<p>
					{#if data.unmapped_expenses > 0}
						{formatEuro(data.unmapped_expenses)} in expenses
					{/if}
					{#if data.unmapped_expenses > 0 && data.unmapped_income > 0}
						and
					{/if}
					{#if data.unmapped_income > 0}
						{formatEuro(data.unmapped_income)} in income
					{/if}
					from bank categories without a mapping.
				</p>
				<button class="btn secondary" onclick={() => goto('/categories')}>Configure Mappings</button>
			</div>
		{/if}
	{/if}
</div>

<style>
	.budget-page { max-width: 100%; }

	.header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		flex-wrap: wrap;
		gap: 1rem;
		margin-bottom: 1.5rem;
	}

	.month-selector {
		display: flex;
		align-items: center;
		gap: 1rem;
	}
	.month-selector h1 {
		margin: 0;
		color: #1a1a1a;
		min-width: 200px;
		text-align: center;
	}
	.nav-btn {
		background: white;
		border: 2px solid #e5e7eb;
		border-radius: 8px;
		padding: 0.5rem 0.75rem;
		cursor: pointer;
		font-size: 1.1rem;
		color: #2d6a4f;
	}
	.nav-btn:hover { background: #f0fdf4; border-color: #2d6a4f; }

	.actions { display: flex; gap: 0.5rem; }

	.btn {
		padding: 0.5rem 1.25rem;
		border: none;
		border-radius: 6px;
		cursor: pointer;
		font-size: 0.9rem;
	}
	.btn.primary { background: #2d6a4f; color: white; }
	.btn.primary:hover { background: #1b4332; }
	.btn.secondary { background: white; color: #2d6a4f; border: 2px solid #2d6a4f; }
	.btn.secondary:hover { background: #f0fdf4; }
	.btn.danger-outline { background: white; color: #dc2626; border: 2px solid #dc2626; }
	.btn.danger-outline:hover { background: #fef2f2; }

	.loading { text-align: center; padding: 3rem; color: #666; }
	.error { background: #fef2f2; color: #dc2626; padding: 1rem; border-radius: 8px; margin-bottom: 1rem; }

	/* Summary cards */
	.summary-cards {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
		gap: 1rem;
		margin-bottom: 1.5rem;
	}
	.card {
		background: white;
		padding: 1.25rem;
		border-radius: 8px;
		text-align: center;
	}
	.card-value { font-size: 1.35rem; font-weight: 700; }
	.card-label { font-size: 0.8rem; color: #666; margin-top: 0.25rem; }
	.income-text { color: #16a34a; }
	.expense-text { color: #dc2626; }
	.positive { color: #16a34a !important; }
	.negative { color: #dc2626 !important; }

	/* Budget vs Actual tables */
	.section {
		background: white;
		padding: 1.5rem;
		border-radius: 8px;
		margin-bottom: 1.5rem;
	}
	h2 { margin: 0 0 1rem; font-size: 1.1rem; color: #1a1a1a; }
	.muted { color: #999; font-style: italic; }

	.bva-table { font-size: 0.9rem; }
	.bva-header {
		display: grid;
		grid-template-columns: 2fr 1fr 1fr 1.2fr 1.5fr;
		padding: 0.5rem 0;
		border-bottom: 2px solid #e5e7eb;
		font-weight: 600;
		font-size: 0.8rem;
		color: #666;
	}
	.bva-row {
		display: grid;
		grid-template-columns: 2fr 1fr 1fr 1.2fr 1.5fr;
		padding: 0.6rem 0;
		border-bottom: 1px solid #f0f0f0;
		align-items: center;
	}
	.bva-row.over-budget { background: #fef2f2; }
	.right { text-align: right; }
	.cat-name { font-weight: 500; }

	.bar-col { padding-left: 0.75rem; }
	.bar-bg {
		height: 8px;
		background: #e5e7eb;
		border-radius: 4px;
	}
	.bar-fill {
		height: 100%;
		border-radius: 4px;
		transition: width 0.3s;
	}
	.income-bar { background: #16a34a; }
	.expense-bar-ok { background: #2d6a4f; }
	.expense-bar-over { background: #dc2626; }

	/* Unmapped warning */
	.unmapped-warning {
		background: #fffbeb;
		border: 1px solid #f59e0b;
		border-radius: 8px;
		padding: 1.25rem;
		margin-top: 1rem;
	}
	.unmapped-warning strong { color: #92400e; }
	.unmapped-warning p { margin: 0.5rem 0; color: #78350f; font-size: 0.9rem; }

	/* No budget state */
	.no-budget {
		text-align: center;
		padding: 2rem 0;
	}
	.no-budget > p { font-size: 1.1rem; color: #666; margin-bottom: 1.5rem; }
	.no-budget-actions { display: flex; gap: 0.75rem; justify-content: center; margin-bottom: 2rem; }
	.actuals-preview { margin-top: 1rem; }

	/* Edit mode */
	.edit-section {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 1.5rem;
	}
	@media (max-width: 768px) {
		.edit-section { grid-template-columns: 1fr; }
	}
	.edit-table { font-size: 0.9rem; }
	.edit-header {
		display: grid;
		grid-template-columns: 2fr 1fr;
		padding: 0.5rem 0;
		border-bottom: 2px solid #e5e7eb;
		font-weight: 600;
		font-size: 0.8rem;
		color: #666;
	}
	.edit-row {
		display: grid;
		grid-template-columns: 2fr 1fr;
		padding: 0.4rem 0;
		border-bottom: 1px solid #f0f0f0;
		align-items: center;
	}
	.edit-row input {
		width: 100%;
		padding: 0.35rem 0.5rem;
		border: 1px solid #ddd;
		border-radius: 4px;
		font-size: 0.9rem;
		text-align: right;
	}
	.edit-row input:focus { outline: none; border-color: #2d6a4f; }

	@media (max-width: 768px) {
		.bva-header, .bva-row {
			grid-template-columns: 1.5fr 1fr 1fr 1fr;
		}
		.bar-col { display: none; }
	}
</style>
