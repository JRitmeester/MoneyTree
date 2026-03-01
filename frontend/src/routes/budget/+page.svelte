<script lang="ts">
	import { goto } from '$app/navigation';
	import {
		getBudget, getBudgetTemplate, updateBudget,
		getBudgetVsActual, getCategories, deleteBudget,
		formatEuro, formatDate,
		type Budget, type BudgetTemplate, type BudgetVsActualSummary, type BudgetVsActualLine, type Category
	} from '$lib/api';

	const MONTH_NAMES = [
		'January', 'February', 'March', 'April', 'May', 'June',
		'July', 'August', 'September', 'October', 'November', 'December'
	];

	// --- State ---
	let now = new Date();
	let currentYear = $state(now.getFullYear());
	let currentMonth = $state(now.getMonth() + 1);

	let activeTab: 'plan' | 'actuals' = $state('plan');
	let loading = $state(true);
	let error: string | null = $state(null);
	let editing = $state(false);

	let templateData: BudgetTemplate | null = $state(null);
	let budgetData: Budget | null = $state(null);
	let bvaData: BudgetVsActualSummary | null = $state(null);
	let categories: Category[] = $state([]);

	// Edit state
	let editLines: { category_id: number; category_name: string; category_type: string; is_fixed: boolean; amount: number }[] = $state([]);
	let updateTemplateChecked = $state(true);
	let addCategoryId: number | null = $state(null);

	// --- Derived ---
	let monthLabel = $derived(`${MONTH_NAMES[currentMonth - 1]} ${currentYear}`);

	// Determine if we have a template set up (has any lines)
	let hasTemplate = $derived(templateData !== null && templateData.lines.length > 0);
	let hasBudget = $derived(budgetData !== null && budgetData.lines.length > 0);

	// Plan tab: split budget lines by type
	let incomeLines = $derived(budgetData?.lines.filter(l => l.category_type === 'income') ?? []);
	let fixedExpenseLines = $derived(budgetData?.lines.filter(l => l.category_type === 'expense' && l.is_fixed) ?? []);
	let flexibleExpenseLines = $derived(budgetData?.lines.filter(l => l.category_type === 'expense' && !l.is_fixed) ?? []);

	let totalIncome = $derived(incomeLines.reduce((s, l) => s + l.amount, 0));
	let totalFixedExpenses = $derived(fixedExpenseLines.reduce((s, l) => s + l.amount, 0));
	let discretionary = $derived(totalIncome - totalFixedExpenses);
	let totalFlexible = $derived(flexibleExpenseLines.reduce((s, l) => s + l.amount, 0));
	let unallocated = $derived(discretionary - totalFlexible);

	// Actuals tab: split BVA lines
	let bvaIncomeLines = $derived(bvaData?.income_lines ?? []);
	let bvaFixedExpenses = $derived(bvaData?.expense_lines.filter(l => l.is_fixed) ?? []);
	let bvaFlexibleExpenses = $derived(bvaData?.expense_lines.filter(l => !l.is_fixed) ?? []);

	// Flat categories for picker
	function flatCategories(cats: Category[], depth = 0): { id: number; name: string; category_type: string; is_fixed: boolean; depth: number }[] {
		let result: { id: number; name: string; category_type: string; is_fixed: boolean; depth: number }[] = [];
		for (const c of cats) {
			result.push({ id: c.id, name: c.name, category_type: c.category_type, is_fixed: c.is_fixed, depth });
			if (c.children?.length) {
				result = result.concat(flatCategories(c.children, depth + 1));
			}
		}
		return result;
	}

	let availableCategories = $derived.by(() => {
		const usedIds = new Set(editLines.map(l => l.category_id));
		return flatCategories(categories).filter(c => !usedIds.has(c.id));
	});

	// --- Loading ---
	async function load() {
		loading = true;
		error = null;
		try {
			const [tpl, bva, cats] = await Promise.all([
				getBudgetTemplate(),
				getBudgetVsActual(currentYear, currentMonth),
				getCategories(),
			]);
			templateData = tpl;
			bvaData = bva;
			categories = cats;

			try {
				budgetData = await getBudget(currentYear, currentMonth);
			} catch {
				budgetData = null;
			}
		} catch (e: any) {
			error = e.message;
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		currentYear; currentMonth;
		load();
	});

	// --- Navigation ---
	function prevMonth() {
		editing = false;
		if (currentMonth === 1) {
			currentMonth = 12;
			currentYear--;
		} else {
			currentMonth--;
		}
	}

	function nextMonth() {
		editing = false;
		if (currentMonth === 12) {
			currentMonth = 1;
			currentYear++;
		} else {
			currentMonth++;
		}
	}

	// --- Edit mode ---
	function startEditing() {
		editLines = [];
		if (budgetData && budgetData.lines.length > 0) {
			for (const line of budgetData.lines) {
				editLines.push({
					category_id: line.category_id,
					category_name: line.category_name,
					category_type: line.category_type,
					is_fixed: line.is_fixed,
					amount: line.amount,
				});
			}
		} else if (templateData && templateData.lines.length > 0) {
			// Pre-fill from template
			for (const line of templateData.lines) {
				editLines.push({
					category_id: line.category_id,
					category_name: line.category_name,
					category_type: line.category_type,
					is_fixed: line.is_fixed,
					amount: line.amount,
				});
			}
		}
		updateTemplateChecked = true;
		addCategoryId = null;
		editing = true;
	}

	function addBudgetLine() {
		if (addCategoryId == null) return;
		const flat = flatCategories(categories);
		const cat = flat.find(c => c.id === addCategoryId);
		if (!cat) return;
		editLines = [...editLines, {
			category_id: cat.id,
			category_name: cat.name,
			category_type: cat.category_type,
			is_fixed: cat.is_fixed,
			amount: 0,
		}];
		addCategoryId = null;
	}

	function removeBudgetLine(index: number) {
		editLines = editLines.filter((_, i) => i !== index);
	}

	async function saveEditing() {
		const lines = editLines
			.filter(l => l.amount > 0)
			.map(l => ({ category_id: l.category_id, amount: l.amount }));

		try {
			await updateBudget(currentYear, currentMonth, { lines }, updateTemplateChecked);
			editing = false;
			await load();
		} catch (e: any) {
			error = e.message;
		}
	}

	function cancelEditing() {
		editing = false;
	}

	async function handleDeleteBudget() {
		if (!confirm('Delete this budget?')) return;
		try {
			await deleteBudget(currentYear, currentMonth);
			budgetData = null;
			await load();
		} catch (e: any) {
			error = e.message;
		}
	}

	// --- Actuals helpers ---
	function progressWidth(line: BudgetVsActualLine): string {
		if (line.budgeted === 0) return '0%';
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
		if (line.difference >= 0) return `${formatEuro(line.difference)} left`;
		return `${formatEuro(Math.abs(line.difference))} over`;
	}

	function isWithinRange(line: BudgetVsActualLine): boolean {
		if (line.budgeted === 0) return line.actual === 0;
		return line.actual <= line.budgeted * 1.05;
	}

	// Edit lines grouped
	let editIncomeLines = $derived(editLines.filter(l => l.category_type === 'income'));
	let editFixedLines = $derived(editLines.filter(l => l.category_type === 'expense' && l.is_fixed));
	let editFlexibleLines = $derived(editLines.filter(l => l.category_type === 'expense' && !l.is_fixed));

	let editTotalIncome = $derived(editIncomeLines.reduce((s, l) => s + l.amount, 0));
	let editTotalFixed = $derived(editFixedLines.reduce((s, l) => s + l.amount, 0));
	let editDiscretionary = $derived(editTotalIncome - editTotalFixed);
	let editTotalFlexible = $derived(editFlexibleLines.reduce((s, l) => s + l.amount, 0));
	let editUnallocated = $derived(editDiscretionary - editTotalFlexible);

	function getEditLineIndex(line: { category_id: number }): number {
		return editLines.findIndex(l => l.category_id === line.category_id);
	}
</script>

<div class="budget-page">
	<!-- Header with month nav -->
	<div class="header">
		<div class="month-selector">
			<button class="nav-btn" onclick={prevMonth}>&larr;</button>
			<h1>{monthLabel}</h1>
			<button class="nav-btn" onclick={nextMonth}>&rarr;</button>
		</div>
		<div class="actions">
			{#if activeTab === 'plan' && !editing && (hasBudget || hasTemplate)}
				<button class="btn primary" onclick={startEditing}>Edit</button>
				{#if hasBudget}
					<button class="btn danger-outline" onclick={handleDeleteBudget}>Delete</button>
				{/if}
			{/if}
			{#if editing}
				<button class="btn primary" onclick={saveEditing}>Save</button>
				<button class="btn secondary" onclick={cancelEditing}>Cancel</button>
			{/if}
		</div>
	</div>

	<!-- Tab bar -->
	<div class="tab-bar">
		<button
			class="tab"
			class:active={activeTab === 'plan'}
			onclick={() => { activeTab = 'plan'; editing = false; }}
		>Plan</button>
		<button
			class="tab"
			class:active={activeTab === 'actuals'}
			onclick={() => { activeTab = 'actuals'; editing = false; }}
		>Actuals</button>
	</div>

	{#if loading}
		<div class="loading">Loading...</div>
	{:else if error}
		<div class="error">{error}</div>
	{:else if activeTab === 'plan'}
		<!-- ================ PLAN TAB ================ -->

		{#if editing}
			<!-- EDIT MODE -->
			<div class="summary-banner">
				<div class="banner-item">
					<span class="banner-value income-text">{formatEuro(editTotalIncome)}</span>
					<span class="banner-label">Income</span>
				</div>
				<div class="banner-item">
					<span class="banner-value expense-text">{formatEuro(editTotalFixed)}</span>
					<span class="banner-label">Fixed Expenses</span>
				</div>
				<div class="banner-item">
					<span class="banner-value">{formatEuro(editDiscretionary)}</span>
					<span class="banner-label">Discretionary</span>
				</div>
				<div class="banner-item">
					<span class="banner-value expense-text">{formatEuro(editTotalFlexible)}</span>
					<span class="banner-label">Allocated</span>
				</div>
				<div class="banner-item">
					<span class="banner-value" class:unallocated-zero={editUnallocated === 0} class:unallocated-nonzero={editUnallocated !== 0}>{formatEuro(editUnallocated)}</span>
					<span class="banner-label">Unallocated</span>
				</div>
			</div>

			<div class="two-col">
				<!-- Left column: Income + Fixed -->
				<div class="col">
					<div class="section">
						<h2>Income</h2>
						<div class="edit-table">
							{#each editIncomeLines as line}
								{@const idx = getEditLineIndex(line)}
								<div class="edit-row">
									<span class="cat-name">{line.category_name}</span>
									<input type="number" step="0.01" min="0" bind:value={editLines[idx].amount} />
									<button class="remove-line-btn" onclick={() => removeBudgetLine(idx)} title="Remove">&times;</button>
								</div>
							{/each}
							{#if editIncomeLines.length === 0}
								<p class="muted">No income categories yet.</p>
							{/if}
						</div>
					</div>

					<div class="section">
						<h2>Fixed Expenses</h2>
						<div class="edit-table">
							{#each editFixedLines as line}
								{@const idx = getEditLineIndex(line)}
								<div class="edit-row">
									<span class="cat-name">{line.category_name}</span>
									<input type="number" step="0.01" min="0" bind:value={editLines[idx].amount} />
									<button class="remove-line-btn" onclick={() => removeBudgetLine(idx)} title="Remove">&times;</button>
								</div>
							{/each}
							{#if editFixedLines.length === 0}
								<p class="muted">No fixed expense categories yet.</p>
							{/if}
						</div>

						<div class="subtotal-row">
							<span>Discretionary</span>
							<span class="subtotal-value">{formatEuro(editDiscretionary)}</span>
						</div>
					</div>
				</div>

				<!-- Right column: Flexible -->
				<div class="col">
					<div class="section">
						<h2>Flexible Expenses</h2>
						<div class="edit-table">
							{#each editFlexibleLines as line}
								{@const idx = getEditLineIndex(line)}
								<div class="edit-row">
									<span class="cat-name">{line.category_name}</span>
									<input type="number" step="0.01" min="0" bind:value={editLines[idx].amount} />
									<button class="remove-line-btn" onclick={() => removeBudgetLine(idx)} title="Remove">&times;</button>
								</div>
							{/each}
							{#if editFlexibleLines.length === 0}
								<p class="muted">No flexible expense categories yet.</p>
							{/if}
						</div>

						<div class="subtotal-row">
							<span>Allocated</span>
							<span class="subtotal-value">{formatEuro(editTotalFlexible)}</span>
						</div>
						<div class="subtotal-row highlight" class:unallocated-zero={editUnallocated === 0} class:unallocated-nonzero={editUnallocated !== 0}>
							<span>Unallocated</span>
							<span class="subtotal-value">{formatEuro(editUnallocated)}</span>
						</div>
					</div>
				</div>
			</div>

			<!-- Add category + template checkbox -->
			<div class="edit-controls">
				<div class="add-line-row">
					<select bind:value={addCategoryId}>
						<option value={null}>-- Add a category --</option>
						{#each availableCategories as cat}
							<option value={cat.id}>{'--'.repeat(cat.depth)}{cat.depth ? ' ' : ''}{cat.name} ({cat.category_type}{cat.is_fixed ? ', fixed' : ''})</option>
						{/each}
					</select>
					<button class="btn primary small" onclick={addBudgetLine} disabled={addCategoryId == null}>+ Add</button>
				</div>
				<label class="template-checkbox">
					<input type="checkbox" bind:checked={updateTemplateChecked} />
					Update template too?
				</label>
			</div>

		{:else if !hasTemplate && !hasBudget}
			<!-- ONBOARDING: No template, no budget -->
			<div class="onboarding">
				<div class="onboarding-card">
					<h2>Set up your budget template</h2>
					<p>Create a monthly budget template that will be used as the starting point for each month. You can always override amounts for individual months.</p>
					<button class="btn primary large" onclick={startEditing}>Add your first budget items</button>
				</div>
			</div>

		{:else}
			<!-- VIEW MODE -->
			<div class="summary-banner">
				<div class="banner-item">
					<span class="banner-value income-text">{formatEuro(totalIncome)}</span>
					<span class="banner-label">Total Income</span>
				</div>
				<div class="banner-item">
					<span class="banner-value expense-text">{formatEuro(totalFixedExpenses)}</span>
					<span class="banner-label">Fixed Expenses</span>
				</div>
				<div class="banner-item">
					<span class="banner-value">{formatEuro(discretionary)}</span>
					<span class="banner-label">Discretionary</span>
				</div>
				<div class="banner-item">
					<span class="banner-value expense-text">{formatEuro(totalFlexible)}</span>
					<span class="banner-label">Allocated</span>
				</div>
				<div class="banner-item">
					<span class="banner-value" class:unallocated-zero={unallocated === 0} class:unallocated-nonzero={unallocated !== 0}>{formatEuro(unallocated)}</span>
					<span class="banner-label">Unallocated</span>
				</div>
			</div>

			<div class="two-col">
				<!-- Left column -->
				<div class="col">
					<div class="section">
						<h2>Income</h2>
						{#if incomeLines.length > 0}
							<div class="plan-table">
								{#each incomeLines as line}
									<div class="plan-row">
										<span class="cat-name">{line.category_name}</span>
										<span class="amount income-text">{formatEuro(line.amount)}</span>
										{#if line.is_overridden}
											<span class="override-badge" title="Overridden from template ({formatEuro(line.template_amount)})">override</span>
										{/if}
									</div>
								{/each}
							</div>
							<div class="subtotal-row">
								<span>Total Income</span>
								<span class="subtotal-value income-text">{formatEuro(totalIncome)}</span>
							</div>
						{:else}
							<p class="muted">No income categories budgeted.</p>
						{/if}
					</div>

					<div class="section">
						<h2>Fixed Expenses</h2>
						{#if fixedExpenseLines.length > 0}
							<div class="plan-table">
								{#each fixedExpenseLines as line}
									<div class="plan-row">
										<span class="cat-name">{line.category_name}</span>
										<span class="amount expense-text">{formatEuro(line.amount)}</span>
										{#if line.is_overridden}
											<span class="override-badge" title="Overridden from template ({formatEuro(line.template_amount)})">override</span>
										{/if}
									</div>
								{/each}
							</div>
							<div class="subtotal-row">
								<span>Total Fixed</span>
								<span class="subtotal-value expense-text">{formatEuro(totalFixedExpenses)}</span>
							</div>
						{:else}
							<p class="muted">No fixed expense categories budgeted.</p>
						{/if}

						<div class="subtotal-row highlight">
							<span>Discretionary</span>
							<span class="subtotal-value">{formatEuro(discretionary)}</span>
						</div>
					</div>
				</div>

				<!-- Right column -->
				<div class="col">
					<div class="section">
						<h2>Flexible Expenses</h2>
						{#if flexibleExpenseLines.length > 0}
							<div class="plan-table">
								{#each flexibleExpenseLines as line}
									<div class="plan-row">
										<span class="cat-name">{line.category_name}</span>
										<span class="amount expense-text">{formatEuro(line.amount)}</span>
										{#if line.is_overridden}
											<span class="override-badge" title="Overridden from template ({formatEuro(line.template_amount)})">override</span>
										{/if}
									</div>
								{/each}
							</div>
							<div class="subtotal-row">
								<span>Allocated</span>
								<span class="subtotal-value expense-text">{formatEuro(totalFlexible)}</span>
							</div>
						{:else}
							<p class="muted">No flexible expense categories budgeted.</p>
						{/if}

						<div class="subtotal-row highlight" class:unallocated-zero={unallocated === 0} class:unallocated-nonzero={unallocated !== 0}>
							<span>Unallocated</span>
							<span class="subtotal-value">{formatEuro(unallocated)}</span>
						</div>
					</div>
				</div>
			</div>
		{/if}

	{:else}
		<!-- ================ ACTUALS TAB ================ -->

		{#if bvaData}
			<!-- Summary cards -->
			<div class="summary-cards">
				<div class="card">
					<div class="card-value income-text">{formatEuro(bvaData.total_budgeted_income)}</div>
					<div class="card-label">Budgeted Income</div>
				</div>
				<div class="card">
					<div class="card-value income-text">{formatEuro(bvaData.total_actual_income)}</div>
					<div class="card-label">Actual Income</div>
				</div>
				<div class="card">
					<div class="card-value expense-text">{formatEuro(bvaData.total_budgeted_expenses)}</div>
					<div class="card-label">Budgeted Expenses</div>
				</div>
				<div class="card">
					<div class="card-value expense-text">{formatEuro(bvaData.total_actual_expenses)}</div>
					<div class="card-label">Actual Expenses</div>
				</div>
				<div class="card" class:positive={bvaData.actual_net >= 0} class:negative={bvaData.actual_net < 0}>
					<div class="card-value">{formatEuro(bvaData.actual_net)}</div>
					<div class="card-label">Net</div>
				</div>
				<div class="card">
					<div class="card-value" style="color: #2d6a4f">{bvaData.savings_rate.toFixed(1)}%</div>
					<div class="card-label">Savings Rate</div>
				</div>
			</div>

			<!-- Income -->
			{#if bvaIncomeLines.length > 0}
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
						{#each bvaIncomeLines as line}
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

			<!-- Fixed Expenses -->
			{#if bvaFixedExpenses.length > 0}
				<div class="section">
					<h2>Fixed Expenses</h2>
					<div class="fixed-list">
						{#each bvaFixedExpenses as line}
							<div class="fixed-row">
								<span class="cat-name">{line.category_name}</span>
								<span class="fixed-amounts">
									<span class="budgeted-amt">{formatEuro(line.budgeted)}</span>
									<span class="actual-amt">{formatEuro(line.actual)}</span>
								</span>
								<span class="fixed-check">
									{#if isWithinRange(line)}
										<span class="check-ok" title="Within budget">&#10003;</span>
									{:else}
										<span class="check-warn" title="Over budget">&#10007;</span>
									{/if}
								</span>
							</div>
						{/each}
					</div>
				</div>
			{/if}

			<!-- Flexible Expenses -->
			{#if bvaFlexibleExpenses.length > 0}
				<div class="section">
					<h2>Flexible Expenses</h2>
					<div class="bva-table">
						<div class="bva-header">
							<span>Category</span>
							<span class="right">Budgeted</span>
							<span class="right">Actual</span>
							<span class="right">Remaining</span>
							<span class="bar-col">Progress</span>
						</div>
						{#each bvaFlexibleExpenses as line}
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

			<!-- Unmapped warning -->
			{#if bvaData.unmapped_expenses > 0 || bvaData.unmapped_income > 0}
				<div class="unmapped-warning">
					<strong>Unmapped transactions</strong>
					<p>
						{#if bvaData.unmapped_expenses > 0}
							{formatEuro(bvaData.unmapped_expenses)} in expenses
						{/if}
						{#if bvaData.unmapped_expenses > 0 && bvaData.unmapped_income > 0}
							and
						{/if}
						{#if bvaData.unmapped_income > 0}
							{formatEuro(bvaData.unmapped_income)} in income
						{/if}
						from bank categories without a mapping.
					</p>
					<button class="btn secondary" onclick={() => goto('/categories')}>Configure Mappings</button>
				</div>
			{/if}
		{:else}
			<p class="muted" style="text-align: center; padding: 2rem">No actuals data available.</p>
		{/if}
	{/if}
</div>

<style>
	.budget-page { max-width: 100%; }

	/* Header */
	.header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		flex-wrap: wrap;
		gap: 1rem;
		margin-bottom: 1rem;
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

	/* Buttons */
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
	.btn.small { padding: 0.4rem 0.75rem; font-size: 0.85rem; }
	.btn.large { padding: 0.75rem 2rem; font-size: 1rem; }

	/* Tab bar */
	.tab-bar {
		display: flex;
		gap: 0;
		border-bottom: 2px solid #e5e7eb;
		margin-bottom: 1.5rem;
	}
	.tab {
		padding: 0.75rem 1.5rem;
		border: none;
		background: none;
		cursor: pointer;
		font-size: 0.95rem;
		font-weight: 500;
		color: #666;
		border-bottom: 3px solid transparent;
		margin-bottom: -2px;
		transition: color 0.15s, border-color 0.15s;
	}
	.tab:hover { color: #2d6a4f; }
	.tab.active {
		color: #2d6a4f;
		border-bottom-color: #2d6a4f;
	}

	/* Loading & Error */
	.loading { text-align: center; padding: 3rem; color: #666; }
	.error { background: #fef2f2; color: #dc2626; padding: 1rem; border-radius: 8px; margin-bottom: 1rem; }

	/* Summary banner (Plan tab) */
	.summary-banner {
		display: flex;
		gap: 1rem;
		margin-bottom: 1.5rem;
		flex-wrap: wrap;
	}
	.banner-item {
		flex: 1;
		min-width: 120px;
		background: white;
		padding: 1rem 1.25rem;
		border-radius: 8px;
		text-align: center;
	}
	.banner-value { font-size: 1.2rem; font-weight: 700; display: block; }
	.banner-label { font-size: 0.75rem; color: #666; margin-top: 0.2rem; display: block; }

	/* Colors */
	.income-text { color: #16a34a; }
	.expense-text { color: #dc2626; }
	.positive { color: #16a34a !important; }
	.negative { color: #dc2626 !important; }
	.unallocated-zero { color: #16a34a !important; }
	.unallocated-nonzero { color: #f59e0b !important; }
	.muted { color: #999; font-style: italic; }

	/* Two-column layout */
	.two-col {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 1.5rem;
	}

	/* Section cards */
	.section {
		background: white;
		padding: 1.5rem;
		border-radius: 8px;
		margin-bottom: 1.5rem;
	}
	.col .section:last-child { margin-bottom: 0; }
	h2 { margin: 0 0 1rem; font-size: 1.1rem; color: #1a1a1a; }

	/* Plan view table */
	.plan-table { font-size: 0.9rem; }
	.plan-row {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: 0.5rem 0;
		border-bottom: 1px solid #f0f0f0;
		gap: 0.5rem;
	}
	.plan-row .cat-name { flex: 1; font-weight: 500; }
	.plan-row .amount { font-weight: 600; white-space: nowrap; }
	.override-badge {
		font-size: 0.65rem;
		background: #f59e0b;
		color: white;
		padding: 0.1rem 0.4rem;
		border-radius: 3px;
		text-transform: uppercase;
		font-weight: 600;
		letter-spacing: 0.03em;
	}

	/* Subtotal rows */
	.subtotal-row {
		display: flex;
		justify-content: space-between;
		padding: 0.75rem 0;
		border-top: 2px solid #e5e7eb;
		margin-top: 0.5rem;
		font-weight: 600;
		font-size: 0.95rem;
	}
	.subtotal-row.highlight {
		background: #f9fafb;
		padding: 0.75rem;
		margin: 0.5rem -1.5rem -1.5rem;
		border-radius: 0 0 8px 8px;
	}
	.subtotal-value { font-weight: 700; }

	/* Edit mode table */
	.edit-table { font-size: 0.9rem; }
	.edit-row {
		display: grid;
		grid-template-columns: 1fr 120px 2rem;
		padding: 0.4rem 0;
		border-bottom: 1px solid #f0f0f0;
		align-items: center;
		gap: 0.5rem;
	}
	.edit-row .cat-name { font-weight: 500; }
	.edit-row input {
		width: 100%;
		padding: 0.35rem 0.5rem;
		border: 1px solid #ddd;
		border-radius: 4px;
		font-size: 0.9rem;
		text-align: right;
	}
	.edit-row input:focus { outline: none; border-color: #2d6a4f; }
	.remove-line-btn {
		background: none;
		border: none;
		color: #9ca3af;
		cursor: pointer;
		font-size: 1.1rem;
		padding: 0;
		line-height: 1;
	}
	.remove-line-btn:hover { color: #dc2626; }

	/* Edit controls (add + template checkbox) */
	.edit-controls {
		background: white;
		padding: 1.25rem 1.5rem;
		border-radius: 8px;
		margin-top: 1.5rem;
		display: flex;
		justify-content: space-between;
		align-items: center;
		flex-wrap: wrap;
		gap: 1rem;
	}
	.add-line-row {
		display: flex;
		gap: 0.5rem;
		align-items: center;
		flex: 1;
		min-width: 250px;
	}
	.add-line-row select {
		flex: 1;
		padding: 0.4rem 0.5rem;
		border: 1px solid #ddd;
		border-radius: 6px;
		font-size: 0.85rem;
	}
	.template-checkbox {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		font-size: 0.9rem;
		color: #444;
		cursor: pointer;
		white-space: nowrap;
	}
	.template-checkbox input { accent-color: #2d6a4f; }

	/* Onboarding state */
	.onboarding {
		display: flex;
		justify-content: center;
		padding: 3rem 1rem;
	}
	.onboarding-card {
		background: white;
		padding: 3rem;
		border-radius: 12px;
		text-align: center;
		max-width: 500px;
	}
	.onboarding-card h2 {
		margin: 0 0 0.75rem;
		font-size: 1.4rem;
		color: #1b4332;
	}
	.onboarding-card p {
		color: #666;
		margin-bottom: 1.5rem;
		line-height: 1.5;
	}

	/* Summary cards (Actuals tab) */
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

	/* Budget vs Actual tables */
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

	/* Fixed expenses list (Actuals tab) */
	.fixed-list { font-size: 0.9rem; }
	.fixed-row {
		display: flex;
		align-items: center;
		padding: 0.6rem 0;
		border-bottom: 1px solid #f0f0f0;
		gap: 1rem;
	}
	.fixed-row .cat-name { flex: 1; font-weight: 500; }
	.fixed-amounts {
		display: flex;
		gap: 1.5rem;
	}
	.budgeted-amt { color: #666; font-size: 0.85rem; }
	.actual-amt { font-weight: 600; }
	.fixed-check { width: 2rem; text-align: center; }
	.check-ok { color: #16a34a; font-size: 1.2rem; font-weight: bold; }
	.check-warn { color: #dc2626; font-size: 1.2rem; font-weight: bold; }

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

	/* Responsive */
	@media (max-width: 768px) {
		.two-col {
			grid-template-columns: 1fr;
		}
		.bva-header, .bva-row {
			grid-template-columns: 1.5fr 1fr 1fr 1fr;
		}
		.bar-col { display: none; }
		.summary-banner {
			flex-direction: column;
		}
		.banner-item {
			min-width: unset;
		}
		.edit-controls {
			flex-direction: column;
			align-items: flex-start;
		}
	}
</style>
