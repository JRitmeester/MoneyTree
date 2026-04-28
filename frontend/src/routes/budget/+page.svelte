<script lang="ts">
	import {
		getBudgets, getBudget, createBudget, updateBudget, patchBudget,
		getBudgetVsActual, getCategories, deleteBudget,
		formatEuro, formatPeriodLabel, updateCategory,
		type Budget, type BudgetSummary, type BudgetVsActualSummary, type BudgetVsActualLine, type Category
	} from '$lib/api';
	import CategoryInput from '$lib/components/CategoryInput.svelte';
	import { buildBudgetTree, buildBvaTree, type BudgetTreeNode, type BvaTreeNode } from '$lib/buildBudgetTree';

	// --- State ---
	let allPeriods: BudgetSummary[] = $state([]);
	let currentPeriodIndex: number = $state(-1);

	let activeTab: 'plan' | 'actuals' = $state(
		(typeof sessionStorage !== 'undefined' && sessionStorage.getItem('budget-tab') === 'actuals') ? 'actuals' : 'plan'
	);
	$effect(() => { sessionStorage.setItem('budget-tab', activeTab); });
	let loading = $state(true);
	let error: string | null = $state(null);

	let budgetData = $state<Budget | null>(null);
	let bvaData = $state<BudgetVsActualSummary | null>(null);
	let categories: Category[] = $state([]);

	// Wizard state
	let wizardOpen = $state(false);
	let wizardStep: 1 | 2 = $state(1);
	let wizardStartDate = $state('');
	let wizardEndDate = $state('');
	let wizardCreating = $state(false);
	type WizardLine = { category_id: number; category_name: string; category_type: string; is_fixed: boolean; amount: number; actualAmount: number; useActual: boolean };
	let wizardLines: WizardLine[] = $state([]);

	// Date editing state
	let editingDates = $state(false);
	let editStartDate = $state('');
	let editEndDate = $state('');
	let savingDates = $state(false);

	// Edit state
	let editLines: { category_id: number; category_name: string; category_type: string; is_fixed: boolean; amount: number; balance: number }[] = $state([]);
	let addIncomeId: number | null = $state(null);
	let addFixedId: number | null = $state(null);
	let addSinkingId: number | null = $state(null);
	let addWishListId: number | null = $state(null);
	let addFlexibleId: number | null = $state(null);

	// --- Derived ---
	let currentPeriod = $derived(currentPeriodIndex >= 0 && currentPeriodIndex < allPeriods.length ? allPeriods[currentPeriodIndex] : null);
	let periodLabel = $derived(currentPeriod ? formatPeriodLabel(currentPeriod.start_date, currentPeriod.end_date) : 'No periods');
	let hasPrev = $derived(currentPeriodIndex < allPeriods.length - 1);
	let hasNext = $derived(currentPeriodIndex > 0);

	let hasBudget = $derived(budgetData !== null && budgetData.lines.length > 0);

	// Actuals tab: split BVA lines
	let bvaIncomeLines = $derived(bvaData?.income_lines ?? []);
	let bvaFixedExpenses = $derived(bvaData?.expense_lines.filter(l => l.is_fixed && l.category_type !== 'savings') ?? []);
	let bvaSavingsExpenses = $derived(bvaData?.expense_lines.filter(l => l.category_type === 'savings') ?? []);
	let bvaSinkingLines = $derived(bvaSavingsExpenses.filter(l => l.is_fixed));
	let bvaWishListLines = $derived(bvaSavingsExpenses.filter(l => !l.is_fixed));
	let bvaFlexibleExpenses = $derived(bvaData?.expense_lines.filter(l => !l.is_fixed && l.category_type !== 'savings') ?? []);

	// Actuals tab: section subtotals
	let bvaIncomeTotals = $derived({ budgeted: bvaIncomeLines.reduce((s, l) => s + l.budgeted, 0), actual: bvaIncomeLines.reduce((s, l) => s + l.actual, 0) });
	let bvaFixedTotals = $derived({ budgeted: bvaFixedExpenses.reduce((s, l) => s + l.budgeted, 0), actual: bvaFixedExpenses.reduce((s, l) => s + l.actual, 0) });
	let bvaSinkingTotals = $derived({ budgeted: bvaSinkingLines.reduce((s, l) => s + l.budgeted, 0), actual: bvaSinkingLines.reduce((s, l) => s + l.actual, 0) });
	let bvaWishListTotals = $derived({ budgeted: bvaWishListLines.reduce((s, l) => s + l.budgeted, 0), actual: bvaWishListLines.reduce((s, l) => s + l.actual, 0) });
	let bvaFlexibleTotals = $derived({ budgeted: bvaFlexibleExpenses.reduce((s, l) => s + l.budgeted, 0), actual: bvaFlexibleExpenses.reduce((s, l) => s + l.actual, 0) });

	// BVA tree views
	let bvaIncomeTree = $derived.by(() => buildBvaTree(bvaIncomeLines));
	let bvaFixedTree = $derived.by(() => buildBvaTree(bvaFixedExpenses));
	let bvaSinkingTree = $derived.by(() => buildBvaTree(bvaSinkingLines));
	let bvaWishListTree = $derived.by(() => buildBvaTree(bvaWishListLines));
	let bvaFlexibleTree = $derived.by(() => buildBvaTree(bvaFlexibleExpenses));

	let bvaExpanded: Record<string, Set<string>> = $state({
		income: new Set(), fixed: new Set(),
		sinking: new Set(), wishlist: new Set(), flexible: new Set(),
	});

	function toggleBvaNode(section: string, path: string) {
		const current = bvaExpanded[section] ?? new Set<string>();
		const next = new Set(current);
		if (next.has(path)) {
			for (const p of next) {
				if (p === path || p.startsWith(path + PATH_SEP)) {
					next.delete(p);
				}
			}
		} else {
			next.add(path);
		}
		bvaExpanded = { ...bvaExpanded, [section]: next };
	}

	function isBvaExpanded(section: string, path: string): boolean {
		return bvaExpanded[section]?.has(path) ?? false;
	}

	// Pacing — only meaningful for flexible spending in the current period
	let periodProgress = $derived.by(() => {
		if (!bvaData) return 0;
		const start = new Date(bvaData.start_date).getTime();
		const end = new Date(bvaData.end_date).getTime();
		const now = Date.now();
		if (now <= start) return 0;
		if (now >= end) return 1;
		return (now - start) / (end - start);
	});

	let isCurrentPeriod = $derived.by(() => {
		if (!bvaData) return false;
		const now = Date.now();
		return now >= new Date(bvaData.start_date).getTime()
			&& now <= new Date(bvaData.end_date).getTime();
	});

	function pacingStatus(line: BudgetVsActualLine): 'on_track' | 'ahead' | 'over' | null {
		if (!isCurrentPeriod || line.budgeted === 0) return null;
		const ratio = line.actual / line.budgeted;
		if (ratio > 1) return 'over';
		if (ratio > periodProgress + 0.10) return 'ahead';
		return 'on_track';
	}

	// Wizard derived
	let wizardIncomeLines = $derived(wizardLines.filter(l => l.category_type === 'income'));
	let wizardFixedLines = $derived(wizardLines.filter(l => l.category_type === 'expense' && l.is_fixed));
	let wizardSavingsLines = $derived(wizardLines.filter(l => l.category_type === 'savings'));
	let wizardSinkingLines = $derived(wizardSavingsLines.filter(l => l.is_fixed));
	let wizardWishListLines = $derived(wizardSavingsLines.filter(l => !l.is_fixed));
	let wizardFlexibleLines = $derived(wizardLines.filter(l => l.category_type === 'expense' && !l.is_fixed));
	let wizardTotalIncome = $derived(wizardIncomeLines.reduce((s, l) => s + l.amount, 0));
	let wizardTotalFixed = $derived(wizardFixedLines.reduce((s, l) => s + l.amount, 0));
	let wizardTotalSavings = $derived(wizardSavingsLines.reduce((s, l) => s + l.amount, 0));
	let wizardTotalFlexible = $derived(wizardFlexibleLines.reduce((s, l) => s + l.amount, 0));
	let wizardDiscretionary = $derived(wizardTotalIncome - wizardTotalFixed - wizardTotalSavings);
	let wizardUnallocated = $derived(wizardDiscretionary - wizardTotalFlexible);

	// Flat categories for picker
	function flatCategories(cats: Category[], parentPath = '', depth = 0): { id: number; name: string; fullPath: string; category_type: string; is_fixed: boolean; depth: number }[] {
		let result: { id: number; name: string; fullPath: string; category_type: string; is_fixed: boolean; depth: number }[] = [];
		for (const c of cats) {
			const fullPath = parentPath ? `${parentPath} > ${c.name}` : c.name;
			result.push({ id: c.id, name: c.name, fullPath, category_type: c.category_type, is_fixed: c.is_fixed, depth });
			if (c.children?.length) {
				result = result.concat(flatCategories(c.children, fullPath, depth + 1));
			}
		}
		return result;
	}

	// --- Helpers ---
	function addDays(dateStr: string, days: number): string {
		const d = new Date(dateStr);
		d.setDate(d.getDate() + days);
		return d.toISOString().split('T')[0];
	}

	function daysBetween(a: string, b: string): number {
		return Math.round((new Date(b).getTime() - new Date(a).getTime()) / 86400000);
	}

	// --- Loading ---
	async function loadPeriods() {
		loading = true;
		error = null;
		try {
			const [periods, cats] = await Promise.all([
				getBudgets(),
				getCategories(),
			]);
			allPeriods = periods;
			categories = cats;

			if (allPeriods.length > 0) {
				if (currentPeriodIndex < 0 || currentPeriodIndex >= allPeriods.length) {
					currentPeriodIndex = 0;
				}
				await loadCurrentPeriod();
			} else {
				currentPeriodIndex = -1;
				budgetData = null;
				bvaData = null;
				loading = false;
			}
		} catch (e: any) {
			error = e.message;
			loading = false;
		}
	}

	async function loadCurrentPeriod() {
		if (!currentPeriod) {
			loading = false;
			return;
		}
		loading = true;
		error = null;
		try {
			const [budget, bva] = await Promise.all([
				getBudget(currentPeriod.id),
				getBudgetVsActual(currentPeriod.id),
			]);
			budgetData = budget;
			bvaData = bva;
		} catch (e: any) {
			error = e.message;
		} finally {
			loading = false;
			syncEditLines();
		}
	}

	loadPeriods();

	// --- Navigation ---
	function prevPeriod() {
		if (!hasPrev) return;
		currentPeriodIndex++;
		loadCurrentPeriod();
	}

	function nextPeriod() {
		if (!hasNext) return;
		currentPeriodIndex--;
		loadCurrentPeriod();
	}

	// --- Wizard ---
	function openWizard() {
		wizardStep = 1;
		// Pre-fill dates from current period
		if (currentPeriod) {
			const duration = daysBetween(currentPeriod.start_date, currentPeriod.end_date);
			wizardStartDate = addDays(currentPeriod.end_date, 1);
			wizardEndDate = addDays(wizardStartDate, duration);
		} else {
			wizardStartDate = '';
			wizardEndDate = '';
		}
		wizardLines = [];
		wizardOpen = true;
	}

	function wizardGoToStep2() {
		if (!wizardStartDate || !wizardEndDate) return;
		// Build lines from current budget
		const actualsByCategory: Record<number, number> = {};
		if (bvaData) {
			for (const line of [...bvaData.income_lines, ...bvaData.expense_lines]) {
				actualsByCategory[line.category_id] = line.actual;
			}
		}

		const sourceLines = budgetData?.lines ?? [];

		wizardLines = sourceLines.map(line => ({
			category_id: line.category_id,
			category_name: line.category_name,
			category_type: line.category_type,
			is_fixed: line.is_fixed,
			amount: line.amount,
			actualAmount: actualsByCategory[line.category_id] ?? 0,
			useActual: false,
		}));
		wizardStep = 2;
	}

	function toggleUseActual(idx: number) {
		const line = wizardLines[idx];
		line.useActual = !line.useActual;
		line.amount = line.useActual ? line.actualAmount : (
			budgetData?.lines.find(l => l.category_id === line.category_id)?.amount ?? 0
		);
		wizardLines = [...wizardLines];
	}

	async function wizardConfirm() {
		wizardCreating = true;
		error = null;
		try {
			const lines = wizardLines
				.filter(l => l.amount > 0)
				.map(l => ({ category_id: l.category_id, amount: l.amount }));
			const created = await createBudget({ start_date: wizardStartDate, end_date: wizardEndDate, lines });
			wizardOpen = false;
			const periods = await getBudgets();
			allPeriods = periods;
			currentPeriodIndex = allPeriods.findIndex(p => p.id === created.id);
			if (currentPeriodIndex < 0) currentPeriodIndex = 0;
			await loadCurrentPeriod();
		} catch (e: any) {
			error = e.message;
		} finally {
			wizardCreating = false;
		}
	}

	// --- Date editing ---
	function startEditingDates() {
		if (!budgetData) return;
		editStartDate = budgetData.start_date;
		editEndDate = budgetData.end_date;
		editingDates = true;
	}

	async function saveDates() {
		if (!budgetData) return;
		savingDates = true;
		error = null;
		try {
			await patchBudget(budgetData.id, { start_date: editStartDate, end_date: editEndDate });
			editingDates = false;
			// Reload to reflect updated dates
			const periods = await getBudgets();
			allPeriods = periods;
			currentPeriodIndex = allPeriods.findIndex(p => p.id === budgetData!.id);
			if (currentPeriodIndex < 0) currentPeriodIndex = 0;
			await loadCurrentPeriod();
		} catch (e: any) {
			error = e.message;
		} finally {
			savingDates = false;
		}
	}

	// --- Sync edit lines from loaded data ---
	function syncEditLines() {
		editLines = (budgetData?.lines ?? []).map(line => ({
			category_id: line.category_id,
			category_name: line.category_name,
			category_type: line.category_type,
			is_fixed: line.is_fixed,
			amount: line.amount,
			balance: line.balance ?? 0,
		}));
		addIncomeId = null;
		addFixedId = null;
		addSinkingId = null;
		addWishListId = null;
		addFlexibleId = null;
	}

	async function persistLines() {
		if (!budgetData) return;
		const lines = editLines
			.filter(l => l.amount > 0)
			.map(l => ({ category_id: l.category_id, amount: l.amount }));
		try {
			await updateBudget(budgetData.id, { lines }, false);
		} catch (e: any) {
			error = e.message;
		}
	}

	async function addLineFromInput(categoryId: number, placement: 'income' | 'fixed' | 'sinking' | 'wishlist' | 'flexible') {
		if (editLines.some(l => l.category_id === categoryId)) return;

		categories = await getCategories();
		const flat = flatCategories(categories);
		const cat = flat.find(c => c.id === categoryId);
		if (!cat) return;

		const newType = placement === 'income' ? 'income' : (placement === 'sinking' || placement === 'wishlist') ? 'savings' : 'expense';
		const newFixed = placement === 'fixed' || placement === 'sinking';

		if (cat.category_type !== newType || cat.is_fixed !== newFixed) {
			try {
				await updateCategory(cat.id, { name: cat.name, category_type: newType, is_fixed: newFixed });
			} catch (e: any) {
				error = e.message;
				return;
			}
		}

		editLines = [...editLines, {
			category_id: cat.id,
			category_name: cat.fullPath,
			category_type: newType,
			is_fixed: newFixed,
			amount: 0,
			balance: 0,
		}];

		if (placement === 'income') addIncomeId = null;
		else if (placement === 'fixed') addFixedId = null;
		else if (placement === 'sinking') addSinkingId = null;
		else if (placement === 'wishlist') addWishListId = null;
		else addFlexibleId = null;

		await persistLines();
	}

	async function removeBudgetLine(index: number) {
		editLines = editLines.filter((_, i) => i !== index);
		await persistLines();
	}

	function handleAmountKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter') {
			(e.target as HTMLInputElement).blur();
		}
	}

	async function handleAmountBlur() {
		await persistLines();
	}

	async function handleDeleteBudget() {
		if (!budgetData) return;
		if (!confirm('Delete this budget period?')) return;
		try {
			await deleteBudget(budgetData.id);
			budgetData = null;
			await loadPeriods();
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
	let editSavingsLines = $derived(editLines.filter(l => l.category_type === 'savings'));
	let editSinkingLines = $derived(editSavingsLines.filter(l => l.is_fixed));
	let editWishListLines = $derived(editSavingsLines.filter(l => !l.is_fixed));
	let editFlexibleLines = $derived(editLines.filter(l => l.category_type === 'expense' && !l.is_fixed));

	let editTotalIncome = $derived(editIncomeLines.reduce((s, l) => s + l.amount, 0));
	let editTotalFixed = $derived(editFixedLines.reduce((s, l) => s + l.amount, 0));
	let editTotalSavings = $derived(editSavingsLines.reduce((s, l) => s + l.amount, 0));
	let editAfterBills = $derived(editTotalIncome - editTotalFixed);
	let editDiscretionary = $derived(editAfterBills - editTotalSavings);
	let editTotalFlexible = $derived(editFlexibleLines.reduce((s, l) => s + l.amount, 0));
	let editUnallocated = $derived(editDiscretionary - editTotalFlexible);

	function getEditLineIndex(line: { category_id: number }): number {
		return editLines.findIndex(l => l.category_id === line.category_id);
	}

	function getWizardLineIndex(line: { category_id: number }): number {
		return wizardLines.findIndex(l => l.category_id === line.category_id);
	}

	// --- Tree view for Plan tab ---
	const PATH_SEP = ' > ';

	let expandedPaths: Record<string, Set<string>> = $state({
		income: new Set(), fixed: new Set(),
		sinking: new Set(), wishlist: new Set(), flexible: new Set(),
	});

	function toggleNode(section: string, path: string) {
		const current = expandedPaths[section] ?? new Set<string>();
		const next = new Set(current);
		if (next.has(path)) {
			for (const p of next) {
				if (p === path || p.startsWith(path + PATH_SEP)) {
					next.delete(p);
				}
			}
		} else {
			next.add(path);
		}
		expandedPaths = { ...expandedPaths, [section]: next };
	}

	function isNodeExpanded(section: string, path: string): boolean {
		return expandedPaths[section]?.has(path) ?? false;
	}

	let incomeTree = $derived.by(() => buildBudgetTree(editIncomeLines, editLines));
	let fixedTree = $derived.by(() => buildBudgetTree(editFixedLines, editLines));
	let sinkingTree = $derived.by(() => buildBudgetTree(editSinkingLines, editLines));
	let wishListTree = $derived.by(() => buildBudgetTree(editWishListLines, editLines));
	let flexibleTree = $derived.by(() => buildBudgetTree(editFlexibleLines, editLines));
</script>

<div class="budget-page">
	<!-- Header -->
	<div class="header">
		<div class="period-selector">
			<button class="nav-btn" onclick={prevPeriod} disabled={!hasPrev}>&larr;</button>
			{#if editingDates}
				<div class="inline-date-edit">
					<input type="date" bind:value={editStartDate} />
					<span class="separator">-</span>
					<input type="date" bind:value={editEndDate} />
					<button class="btn primary small" onclick={saveDates} disabled={savingDates || !editStartDate || !editEndDate}>
						{savingDates ? '...' : 'Save'}
					</button>
					<button class="btn secondary small" onclick={() => { editingDates = false; }}>Cancel</button>
				</div>
			{:else}
				<h1>{periodLabel}</h1>
				{#if currentPeriod}
					<button class="edit-dates-btn" onclick={startEditingDates} title="Edit dates">&#9998;</button>
				{/if}
			{/if}
			<button class="nav-btn" onclick={nextPeriod} disabled={!hasNext}>&rarr;</button>
		</div>
		<div class="actions">
			<button class="btn secondary" onclick={openWizard}>New Period</button>
			{#if currentPeriod && hasBudget}
				<button class="btn danger-text" onclick={handleDeleteBudget}>Delete</button>
			{/if}
		</div>
	</div>

	<!-- Wizard Modal -->
	{#if wizardOpen}
		<div class="wizard-backdrop" onclick={() => { wizardOpen = false; }}>
			<div class="wizard-modal" onclick={(e) => e.stopPropagation()}>
				<div class="wizard-header">
					<h2>Create New Period</h2>
					<button class="wizard-close" onclick={() => { wizardOpen = false; }}>&times;</button>
				</div>

				{#if wizardStep === 1}
					<!-- Step 1: Dates -->
					<div class="wizard-body">
						<p class="wizard-desc">Choose the date range for the new budget period.</p>
						<div class="wizard-dates">
							<label>
								Start date
								<input type="date" bind:value={wizardStartDate} />
							</label>
							<label>
								End date
								<input type="date" bind:value={wizardEndDate} />
							</label>
						</div>
					</div>
					<div class="wizard-footer">
						<button class="btn secondary" onclick={() => { wizardOpen = false; }}>Cancel</button>
						<button class="btn primary" onclick={wizardGoToStep2} disabled={!wizardStartDate || !wizardEndDate}>Next</button>
					</div>

				{:else}
					<!-- Step 2: Lines -->
					<div class="wizard-body">
						<p class="wizard-desc">Configure budget amounts. For flexible expenses, you can use the actual spent amount from the current period.</p>

						<div class="wizard-summary">
							<span class="ws-item"><span class="ws-label">Income</span> <span class="ws-value income-text">{formatEuro(wizardTotalIncome)}</span></span>
							<span class="ws-item"><span class="ws-label">Bills</span> <span class="ws-value expense-text">{formatEuro(wizardTotalFixed)}</span></span>
							<span class="ws-item"><span class="ws-label">Savings</span> <span class="ws-value expense-text">{formatEuro(wizardTotalSavings)}</span></span>
							<span class="ws-item"><span class="ws-label">Flexible</span> <span class="ws-value expense-text">{formatEuro(wizardTotalFlexible)}</span></span>
							<span class="ws-item"><span class="ws-label">Unallocated</span> <span class="ws-value" class:unallocated-zero={wizardUnallocated === 0} class:unallocated-nonzero={wizardUnallocated !== 0}>{formatEuro(wizardUnallocated)}</span></span>
						</div>

						{#if wizardIncomeLines.length > 0}
							<h3>Income</h3>
							<div class="wizard-lines">
								{#each wizardIncomeLines as line}
									{@const idx = getWizardLineIndex(line)}
									<div class="wizard-line-row">
										<span class="cat-name">{line.category_name}</span>
										<input type="number" step="0.01" min="0" bind:value={wizardLines[idx].amount} />
									</div>
								{/each}
							</div>
						{/if}

						{#if wizardFixedLines.length > 0}
							<h3>Fixed Bills</h3>
							<div class="wizard-lines">
								{#each wizardFixedLines as line}
									{@const idx = getWizardLineIndex(line)}
									<div class="wizard-line-row">
										<span class="cat-name">{line.category_name}</span>
										<input type="number" step="0.01" min="0" bind:value={wizardLines[idx].amount} />
									</div>
								{/each}
							</div>
						{/if}

						{#if wizardSinkingLines.length > 0}
							<h3>Sinking Funds</h3>
							<div class="wizard-lines">
								{#each wizardSinkingLines as line}
									{@const idx = getWizardLineIndex(line)}
									<div class="wizard-line-row">
										<span class="cat-name">{line.category_name}</span>
										<input type="number" step="0.01" min="0" bind:value={wizardLines[idx].amount} />
									</div>
								{/each}
							</div>
						{/if}

						{#if wizardWishListLines.length > 0}
							<h3>Saving Goals</h3>
							<div class="wizard-lines">
								{#each wizardWishListLines as line}
									{@const idx = getWizardLineIndex(line)}
									<div class="wizard-line-row">
										<span class="cat-name">{line.category_name}</span>
										<input type="number" step="0.01" min="0" bind:value={wizardLines[idx].amount} />
									</div>
								{/each}
							</div>
						{/if}

						{#if wizardFlexibleLines.length > 0}
							<h3>Flexible Spending</h3>
							<div class="wizard-lines">
								{#each wizardFlexibleLines as line}
									{@const idx = getWizardLineIndex(line)}
									<div class="wizard-line-row">
										<span class="cat-name">{line.category_name}</span>
										<input type="number" step="0.01" min="0" bind:value={wizardLines[idx].amount} />
										{#if line.actualAmount > 0}
											<label class="actual-toggle">
												<input type="checkbox" checked={line.useActual} onchange={() => toggleUseActual(idx)} />
												<span class="actual-label">Actual ({formatEuro(line.actualAmount)})</span>
											</label>
										{/if}
									</div>
								{/each}
							</div>
						{/if}

						{#if wizardLines.length === 0}
							<p class="muted">No budget lines to copy. The new period will be created empty.</p>
						{/if}
					</div>
					<div class="wizard-footer">
						<button class="btn secondary" onclick={() => { wizardStep = 1; }}>Back</button>
						<button class="btn primary" onclick={wizardConfirm} disabled={wizardCreating}>
							{wizardCreating ? 'Creating...' : 'Create Period'}
						</button>
					</div>
				{/if}
			</div>
		</div>
	{/if}

	<!-- Tab bar -->
	<div class="tab-bar">
		<button
			class="tab"
			class:active={activeTab === 'plan'}
			onclick={() => { activeTab = 'plan'; }}
		>Plan</button>
		<button
			class="tab"
			class:active={activeTab === 'actuals'}
			onclick={() => { activeTab = 'actuals'; }}
		>Actuals</button>
	</div>

	{#if loading}
		<div class="loading">Loading...</div>
	{:else if error}
		<div class="error">{error}</div>
	{:else if !currentPeriod}
		<!-- No periods exist yet -->
		<div class="onboarding">
			<div class="onboarding-card">
				<h2>Create your first budget period</h2>
				<p>Define a date range for your budget period (e.g. your salary cycle). You can always add more periods later.</p>
				<button class="btn primary large" onclick={openWizard}>Create first period</button>
			</div>
		</div>
	{:else if activeTab === 'plan'}
		<!-- ================ PLAN TAB ================ -->

		{#snippet budgetTreeNode(node: BudgetTreeNode, section: string, depth: number, showBalance: boolean)}
			{#if node.children.length > 0}
				<button
					class="tree-row tree-parent"
					style="padding-left: {0.5 + depth * 1.25}rem"
					onclick={() => toggleNode(section, node.path)}
				>
					<span class="tree-toggle">{isNodeExpanded(section, node.path) ? '▼' : '▶'}</span>
					<span class="cat-name tree-name">{node.name}</span>
					{#if node.categoryId !== null}
						{@const idx = editLines.findIndex(l => l.category_id === node.categoryId)}
						<input type="number" step="0.01" min="0" bind:value={editLines[idx].amount}
							onblur={handleAmountBlur} onkeydown={handleAmountKeydown}
							onclick={(e) => e.stopPropagation()} />
						{#if showBalance && editLines[idx].balance > 0}
							<span class="balance-badge">{formatEuro(editLines[idx].balance)}</span>
						{/if}
						<button class="remove-line-btn" onclick={(e) => { e.stopPropagation(); removeBudgetLine(idx); }} title="Remove">&times;</button>
					{:else}
						<span class="tree-total">{formatEuro(node.total)}</span>
					{/if}
				</button>
				{#if isNodeExpanded(section, node.path)}
					<div class="children-panel" style="margin-left: {0.5 + depth * 0.5}rem">
						{#each node.children as child (child.path)}
							{@render budgetTreeNode(child, section, depth + 1, showBalance)}
						{/each}
					</div>
				{/if}
			{:else if node.categoryId !== null}
				{@const idx = editLines.findIndex(l => l.category_id === node.categoryId)}
				<div class="tree-row tree-leaf" style="padding-left: {0.5 + depth * 1.25}rem">
					<span class="cat-name tree-name">{node.name}</span>
					<input type="number" step="0.01" min="0" bind:value={editLines[idx].amount}
						onblur={handleAmountBlur} onkeydown={handleAmountKeydown} />
					{#if showBalance && editLines[idx].balance > 0}
						<span class="balance-badge">{formatEuro(editLines[idx].balance)}</span>
					{/if}
					<button class="remove-line-btn" onclick={() => removeBudgetLine(idx)} title="Remove">&times;</button>
				</div>
			{/if}
		{/snippet}

		<div class="budget-grid">
			<div class="section">
				<h2>Income</h2>
				<div class="edit-table">
					{#each incomeTree as node (node.path)}
						{@render budgetTreeNode(node, 'income', 0, false)}
					{/each}
					<div class="edit-row add-row">
						<div class="add-input-wrap">
							<CategoryInput
								value={addIncomeId}
								onchange={(id) => { if (id) addLineFromInput(id, 'income'); }}
								placeholder="Add category..."
							/>
						</div>
					</div>
				</div>
				<div class="subtotal-row">
					<span>Total</span>
					<span class="subtotal-value income-text">{formatEuro(editTotalIncome)}</span>
				</div>
			</div>

			<div class="section">
				<h2>Fixed Bills</h2>
				<div class="edit-table">
					{#each fixedTree as node (node.path)}
						{@render budgetTreeNode(node, 'fixed', 0, false)}
					{/each}
					<div class="edit-row add-row">
						<div class="add-input-wrap">
							<CategoryInput
								value={addFixedId}
								onchange={(id) => { if (id) addLineFromInput(id, 'fixed'); }}
								placeholder="Add category..."
							/>
						</div>
					</div>
				</div>
				<div class="subtotal-row">
					<span>After bills</span>
					<span class="subtotal-value">{formatEuro(editAfterBills)}</span>
				</div>
			</div>

			<div class="savings-column">
				<div class="section">
					<h2>Sinking Funds</h2>
					<div class="edit-table">
						{#each sinkingTree as node (node.path)}
							{@render budgetTreeNode(node, 'sinking', 0, true)}
						{/each}
						<div class="edit-row add-row">
							<div class="add-input-wrap">
								<CategoryInput
									value={addSinkingId}
									onchange={(id) => { if (id) addLineFromInput(id, 'sinking'); }}
									placeholder="Add sinking fund..."
								/>
							</div>
						</div>
					</div>
				</div>

				<div class="section">
					<h2>Saving Goals</h2>
					<div class="edit-table">
						{#each wishListTree as node (node.path)}
							{@render budgetTreeNode(node, 'wishlist', 0, true)}
						{/each}
						<div class="edit-row add-row">
							<div class="add-input-wrap">
								<CategoryInput
									value={addWishListId}
									onchange={(id) => { if (id) addLineFromInput(id, 'wishlist'); }}
									placeholder="Add saving goal..."
								/>
							</div>
						</div>
					</div>
				</div>

				<div class="subtotal-row savings-subtotal">
					<span>Discretionary</span>
					<span class="subtotal-value">{formatEuro(editDiscretionary)}</span>
				</div>
			</div>

			<div class="section">
				<h2>Flexible Spending</h2>
				<div class="edit-table">
					{#each flexibleTree as node (node.path)}
						{@render budgetTreeNode(node, 'flexible', 0, false)}
					{/each}
					<div class="edit-row add-row">
						<div class="add-input-wrap">
							<CategoryInput
								value={addFlexibleId}
								onchange={(id) => { if (id) addLineFromInput(id, 'flexible'); }}
								placeholder="Add category..."
							/>
						</div>
					</div>
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

			<!-- BVA tree snippets -->
			{#snippet bvaParentRow(node: BvaTreeNode, section: string, depth: number, cols: number)}
				<button class="bva-row bva-row-parent" onclick={() => toggleBvaNode(section, node.path)}>
					<span class="cat-name" style="padding-left: {depth * 1.25}rem">
						<span class="tree-toggle">{isBvaExpanded(section, node.path) ? '▼' : '▶'}</span>
						{node.name}
					</span>
					<span class="right">{formatEuro(node.budgeted)}</span>
					<span class="right">{formatEuro(node.actual)}</span>
					<span class="right"></span>
					{#if cols === 5}<span class="bar-col"></span>{/if}
				</button>
			{/snippet}

			{#snippet bvaIncomeNode(node: BvaTreeNode, section: string, depth: number)}
				{#if node.children.length > 0}
					{@render bvaParentRow(node, section, depth, 5)}
					{#if isBvaExpanded(section, node.path)}
						<div class="bva-children">
							{#each node.children as child (child.path)}
								{@render bvaIncomeNode(child, section, depth + 1)}
							{/each}
						</div>
					{/if}
				{:else if node.categoryId !== null}
					{@const line = bvaIncomeLines.find((l: BudgetVsActualLine) => l.category_id === node.categoryId)}
					{#if line && bvaData}
						<a href="/spending/category/{line.category_id}?date_from={bvaData.start_date}&date_to={bvaData.end_date}" class="bva-row bva-row-link">
							<span class="cat-name" style="padding-left: {depth * 1.25}rem">{node.name}</span>
							<span class="right">{formatEuro(line.budgeted)}</span>
							<span class="right">{formatEuro(line.actual)}</span>
							<span class="right" class:positive={line.difference >= 0} class:negative={line.difference < 0}>{formatDiff(line)}</span>
							<span class="bar-col"><div class="bar-bg"><div class="bar-fill income-bar" style="width: {progressWidth(line)}"></div></div></span>
						</a>
					{/if}
				{/if}
			{/snippet}

			{#snippet bvaFixedNode(node: BvaTreeNode, section: string, depth: number)}
				{#if node.children.length > 0}
					{@render bvaParentRow(node, section, depth, 4)}
					{#if isBvaExpanded(section, node.path)}
						<div class="bva-children">
							{#each node.children as child (child.path)}
								{@render bvaFixedNode(child, section, depth + 1)}
							{/each}
						</div>
					{/if}
				{:else if node.categoryId !== null}
					{@const line = bvaFixedExpenses.find((l: BudgetVsActualLine) => l.category_id === node.categoryId)}
					{#if line && bvaData}
						<a href="/spending/category/{line.category_id}?date_from={bvaData.start_date}&date_to={bvaData.end_date}" class="bva-row bva-row-link">
							<span class="cat-name" style="padding-left: {depth * 1.25}rem">{node.name}</span>
							<span class="right">{formatEuro(line.budgeted)}</span>
							<span class="right">{formatEuro(line.actual)}</span>
							<span class="right">
								{#if isWithinRange(line)}<span class="check-ok" title="Within budget">&#10003;</span>{:else}<span class="check-warn" title="Over budget">&#10007;</span>{/if}
							</span>
						</a>
					{/if}
				{/if}
			{/snippet}

			{#snippet bvaSavingsNode(node: BvaTreeNode, section: string, depth: number, lines: typeof bvaSinkingLines)}
				{#if node.children.length > 0}
					{@render bvaParentRow(node, section, depth, 4)}
					{#if isBvaExpanded(section, node.path)}
						<div class="bva-children">
							{#each node.children as child (child.path)}
								{@render bvaSavingsNode(child, section, depth + 1, lines)}
							{/each}
						</div>
					{/if}
				{:else if node.categoryId !== null}
					{@const line = lines.find((l: BudgetVsActualLine) => l.category_id === node.categoryId)}
					{#if line && bvaData}
						<a href="/spending/category/{line.category_id}?date_from={bvaData.start_date}&date_to={bvaData.end_date}" class="bva-row bva-row-link">
							<span class="cat-name" style="padding-left: {depth * 1.25}rem">{node.name}</span>
							<span class="right">{formatEuro(line.budgeted)}</span>
							<span class="right">{formatEuro(line.actual)}</span>
							<span class="right balance-text">{formatEuro(line.balance)}</span>
						</a>
					{/if}
				{/if}
			{/snippet}

			{#snippet bvaFlexibleNode(node: BvaTreeNode, section: string, depth: number)}
				{#if node.children.length > 0}
					{@render bvaParentRow(node, section, depth, 5)}
					{#if isBvaExpanded(section, node.path)}
						<div class="bva-children">
							{#each node.children as child (child.path)}
								{@render bvaFlexibleNode(child, section, depth + 1)}
							{/each}
						</div>
					{/if}
				{:else if node.categoryId !== null}
					{@const line = bvaFlexibleExpenses.find((l: BudgetVsActualLine) => l.category_id === node.categoryId)}
					{#if line && bvaData}
						<a href="/spending/category/{line.category_id}?date_from={bvaData.start_date}&date_to={bvaData.end_date}" class="bva-row bva-row-link" class:over-budget={isOverBudget(line)}>
							<span class="cat-name" style="padding-left: {depth * 1.25}rem">{node.name}</span>
							<span class="right">{formatEuro(line.budgeted)}</span>
							<span class="right">{formatEuro(line.actual)}</span>
							<span class="right" class:positive={line.difference >= 0} class:negative={line.difference < 0}>{formatDiff(line)}</span>
							<span class="bar-col">
								<div class="bar-bg">
									<div class="bar-fill" class:expense-bar-ok={!isOverBudget(line)} class:expense-bar-over={isOverBudget(line)} style="width: {progressWidth(line)}"></div>
									{#if isCurrentPeriod && line.budgeted > 0}
										<div class="pace-marker" style="left: {periodProgress * 100}%"></div>
									{/if}
								</div>
								{#if pacingStatus(line) === 'ahead'}
									<span class="pace-label pace-ahead">Ahead of pace</span>
								{/if}
							</span>
						</a>
					{/if}
				{/if}
			{/snippet}

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
						{#each bvaIncomeTree as node (node.path)}
							{@render bvaIncomeNode(node, 'income', 0)}
						{/each}
						{#if bvaIncomeLines.length > 1}
							<div class="bva-row bva-subtotal">
								<span class="cat-name">Total</span>
								<span class="right">{formatEuro(bvaIncomeTotals.budgeted)}</span>
								<span class="right">{formatEuro(bvaIncomeTotals.actual)}</span>
								<span class="right"></span>
								<span class="bar-col"></span>
							</div>
						{/if}
					</div>
				</div>
			{/if}

			<!-- Fixed Bills -->
			{#if bvaFixedExpenses.length > 0}
				<div class="section">
					<h2>Fixed Bills</h2>
					<div class="bva-table bva-table-fixed">
						<div class="bva-header">
							<span>Category</span>
							<span class="right">Budgeted</span>
							<span class="right">Actual</span>
							<span class="right">Status</span>
						</div>
						{#each bvaFixedTree as node (node.path)}
							{@render bvaFixedNode(node, 'fixed', 0)}
						{/each}
						{#if bvaFixedExpenses.length > 1}
							<div class="bva-row bva-subtotal">
								<span class="cat-name">Total</span>
								<span class="right">{formatEuro(bvaFixedTotals.budgeted)}</span>
								<span class="right">{formatEuro(bvaFixedTotals.actual)}</span>
								<span class="right"></span>
							</div>
						{/if}
					</div>
				</div>
			{/if}

			<!-- Savings -->
			{#if bvaSinkingLines.length > 0}
				<div class="section">
					<h2>Sinking Funds</h2>
					<div class="bva-table bva-table-fixed">
						<div class="bva-header">
							<span>Category</span>
							<span class="right">Budgeted</span>
							<span class="right">Actual</span>
							<span class="right">Balance</span>
						</div>
						{#each bvaSinkingTree as node (node.path)}
							{@render bvaSavingsNode(node, 'sinking', 0, bvaSinkingLines)}
						{/each}
						{#if bvaSinkingLines.length > 1}
							<div class="bva-row bva-subtotal">
								<span class="cat-name">Total</span>
								<span class="right">{formatEuro(bvaSinkingTotals.budgeted)}</span>
								<span class="right">{formatEuro(bvaSinkingTotals.actual)}</span>
								<span class="right"></span>
							</div>
						{/if}
					</div>
				</div>
			{/if}

			{#if bvaWishListLines.length > 0}
				<div class="section">
					<h2>Saving Goals</h2>
					<div class="bva-table bva-table-fixed">
						<div class="bva-header">
							<span>Category</span>
							<span class="right">Budgeted</span>
							<span class="right">Actual</span>
							<span class="right">Balance</span>
						</div>
						{#each bvaWishListTree as node (node.path)}
							{@render bvaSavingsNode(node, 'wishlist', 0, bvaWishListLines)}
						{/each}
						{#if bvaWishListLines.length > 1}
							<div class="bva-row bva-subtotal">
								<span class="cat-name">Total</span>
								<span class="right">{formatEuro(bvaWishListTotals.budgeted)}</span>
								<span class="right">{formatEuro(bvaWishListTotals.actual)}</span>
								<span class="right"></span>
							</div>
						{/if}
					</div>
				</div>
			{/if}

			<!-- Flexible Spending -->
			{#if bvaFlexibleExpenses.length > 0}
				<div class="section">
					<h2>Flexible Spending</h2>
					<div class="bva-table">
						<div class="bva-header">
							<span>Category</span>
							<span class="right">Budgeted</span>
							<span class="right">Actual</span>
							<span class="right">Remaining</span>
							<span class="bar-col">Progress</span>
						</div>
						{#each bvaFlexibleTree as node (node.path)}
							{@render bvaFlexibleNode(node, 'flexible', 0)}
						{/each}
						{#if bvaFlexibleExpenses.length > 1}
							<div class="bva-row bva-subtotal">
								<span class="cat-name">Total</span>
								<span class="right">{formatEuro(bvaFlexibleTotals.budgeted)}</span>
								<span class="right">{formatEuro(bvaFlexibleTotals.actual)}</span>
								<span class="right"></span>
								<span class="bar-col"></span>
							</div>
						{/if}
					</div>
				</div>
			{/if}

			<!-- Uncategorized -->
			{#if bvaData.unmapped_expenses > 0 || bvaData.unmapped_income > 0}
				<div class="section unmapped-section">
					<h2>Uncategorized</h2>
					<p class="unmapped-desc">Transactions without a category are not included in the sections above.</p>
					{#if bvaData.unmapped_income > 0}
						<div class="unmapped-row">
							<span>Income</span>
							<span>{formatEuro(bvaData.unmapped_income)}</span>
						</div>
					{/if}
					{#if bvaData.unmapped_expenses > 0}
						<div class="unmapped-row">
							<span>Expenses</span>
							<span>{formatEuro(bvaData.unmapped_expenses)}</span>
						</div>
					{/if}
					<a href="/uncategorized" class="unmapped-link">Categorize transactions &rarr;</a>
				</div>
			{/if}

			{:else}
			<p class="muted" style="text-align: center; padding: 2rem">No actuals data available.</p>
		{/if}
	{/if}
</div>

<style>
	.budget-page {
		max-width: 100%;
		margin: 0 auto;
	}
	:global(main:has(.budget-page)) {
		max-width: 1600px;
	}

	/* Header */
	.header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		flex-wrap: wrap;
		gap: 1rem;
		margin-bottom: 1rem;
	}
	.period-selector {
		display: flex;
		align-items: center;
		gap: 1rem;
	}
	.period-selector h1 {
		margin: 0;
		color: #1a1a1a;
		min-width: 260px;
		text-align: center;
		font-size: 1.4rem;
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
	.nav-btn:hover:not(:disabled) { background: #f0fdf4; border-color: #2d6a4f; }
	.nav-btn:disabled { opacity: 0.3; cursor: default; }
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
	.btn.primary:disabled { opacity: 0.5; cursor: default; }
	.btn.secondary { background: white; color: #2d6a4f; border: 2px solid #2d6a4f; }
	.btn.secondary:hover { background: #f0fdf4; }
	.btn.danger-outline { background: white; color: #dc2626; border: 2px solid #dc2626; }
	.btn.danger-outline:hover { background: #fef2f2; }
	.btn.danger-text { background: none; color: #999; border: none; font-size: 0.8rem; }
	.btn.danger-text:hover { color: #dc2626; }
	.btn.small { padding: 0.4rem 0.75rem; font-size: 0.85rem; }
	.btn.large { padding: 0.75rem 2rem; font-size: 1rem; }

	/* Inline date editing */
	.inline-date-edit {
		display: flex;
		align-items: center;
		gap: 0.5rem;
	}
	.inline-date-edit input[type="date"] {
		padding: 0.35rem 0.5rem;
		border: 1px solid #ddd;
		border-radius: 6px;
		font-size: 0.85rem;
	}
	.inline-date-edit input[type="date"]:focus { outline: none; border-color: #2d6a4f; }
	.inline-date-edit .separator { color: #999; font-size: 0.85rem; }
	.edit-dates-btn {
		background: none;
		border: none;
		cursor: pointer;
		font-size: 1rem;
		color: #9ca3af;
		padding: 0.25rem;
		line-height: 1;
	}
	.edit-dates-btn:hover { color: #2d6a4f; }

	/* Wizard modal */
	.wizard-backdrop {
		position: fixed;
		inset: 0;
		background: rgba(0,0,0,0.4);
		display: flex;
		align-items: center;
		justify-content: center;
		z-index: 100;
	}
	.wizard-modal {
		background: white;
		border-radius: 12px;
		width: 90%;
		max-width: 600px;
		max-height: 85vh;
		display: flex;
		flex-direction: column;
	}
	.wizard-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: 1.25rem 1.5rem;
		border-bottom: 1px solid #e5e7eb;
	}
	.wizard-header h2 { margin: 0; font-size: 1.15rem; color: #1a1a1a; }
	.wizard-close {
		background: none;
		border: none;
		font-size: 1.5rem;
		cursor: pointer;
		color: #9ca3af;
		line-height: 1;
	}
	.wizard-close:hover { color: #1a1a1a; }
	.wizard-body {
		padding: 1.5rem;
		overflow-y: auto;
		flex: 1;
	}
	.wizard-desc { margin: 0 0 1.25rem; color: #666; font-size: 0.9rem; line-height: 1.5; }
	.wizard-dates {
		display: flex;
		gap: 1.5rem;
		flex-wrap: wrap;
	}
	.wizard-dates label {
		display: flex;
		flex-direction: column;
		gap: 0.3rem;
		font-size: 0.85rem;
		color: #666;
		flex: 1;
		min-width: 150px;
	}
	.wizard-dates input[type="date"] {
		padding: 0.5rem;
		border: 1px solid #ddd;
		border-radius: 6px;
		font-size: 0.9rem;
	}
	.wizard-dates input[type="date"]:focus { outline: none; border-color: #2d6a4f; }
	.wizard-footer {
		padding: 1rem 1.5rem;
		border-top: 1px solid #e5e7eb;
		display: flex;
		justify-content: flex-end;
		gap: 0.5rem;
	}
	.wizard-summary {
		display: flex;
		gap: 1rem;
		margin-bottom: 1.25rem;
		flex-wrap: wrap;
	}
	.ws-item {
		flex: 1;
		min-width: 100px;
		background: #f9fafb;
		padding: 0.6rem 0.75rem;
		border-radius: 6px;
		text-align: center;
	}
	.ws-label { display: block; font-size: 0.7rem; color: #666; }
	.ws-value { display: block; font-size: 1rem; font-weight: 700; margin-top: 0.1rem; }
	.wizard-body h3 { margin: 1rem 0 0.5rem; font-size: 0.95rem; color: #1a1a1a; }
	.wizard-body h3:first-of-type { margin-top: 0; }
	.wizard-lines { font-size: 0.9rem; }
	.wizard-line-row {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		padding: 0.4rem 0;
		border-bottom: 1px solid #f0f0f0;
	}
	.wizard-line-row .cat-name { flex: 1; font-weight: 500; }
	.wizard-line-row input[type="number"] {
		width: 110px;
		padding: 0.35rem 0.5rem;
		border: 1px solid #ddd;
		border-radius: 4px;
		font-size: 0.9rem;
		text-align: right;
	}
	.wizard-line-row input[type="number"]:focus { outline: none; border-color: #2d6a4f; }
	.actual-toggle {
		display: flex;
		align-items: center;
		gap: 0.3rem;
		cursor: pointer;
		white-space: nowrap;
	}
	.actual-toggle input[type="checkbox"] { accent-color: #2d6a4f; }
	.actual-label { font-size: 0.75rem; color: #666; }

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

	/* Colors */
	.income-text { color: #16a34a; }
	.expense-text { color: #dc2626; }
	.positive { color: #16a34a !important; }
	.negative { color: #dc2626 !important; }
	.unallocated-zero { color: #16a34a !important; }
	.unallocated-nonzero { color: #f59e0b !important; }
	.muted { color: #999; font-style: italic; }

	/* Budget grid layout */
	.budget-grid {
		display: grid;
		grid-template-columns: repeat(4, 1fr);
		gap: 1rem;
		align-items: start;
	}

	/* Section cards */
	.section {
		background: white;
		padding: 1.25rem;
		border-radius: 8px;
	}
	h2 { margin: 0 0 1rem; font-size: 1.1rem; color: #1a1a1a; }

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
		display: flex;
		padding: 0.4rem 0;
		border-bottom: 1px solid #f0f0f0;
		align-items: center;
		gap: 0.5rem;
	}
	.edit-row .cat-name { font-weight: 500; flex: 1; min-width: 0; }
	.edit-row input[type="number"] {
		width: 80px;
		padding: 0.35rem 0.5rem;
		border: 1px solid #ddd;
		border-radius: 4px;
		font-size: 0.9rem;
		text-align: right;
	}
	.edit-row input[type="number"]:focus { outline: none; border-color: #2d6a4f; }
	.remove-line-btn {
		background: none;
		border: none;
		color: #9ca3af;
		cursor: pointer;
		font-size: 1.1rem;
		padding: 0;
		line-height: 1;
		flex-shrink: 0;
	}
	.remove-line-btn:hover { color: #dc2626; }
	.add-row { border-bottom: none; }

	/* Tree view */
	.tree-row {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		padding: 0.4rem 0;
		border-bottom: 1px solid #f0f0f0;
	}
	.tree-parent {
		background: none;
		border: none;
		width: 100%;
		text-align: left;
		cursor: pointer;
		border-radius: 4px;
		font-size: inherit;
	}
	.tree-parent:hover { background: #f9fafb; }
	.tree-leaf { font-size: inherit; }
	.tree-toggle {
		display: inline-block;
		width: 1em;
		font-size: 0.65rem;
		color: #999;
		flex-shrink: 0;
	}
	.tree-name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	.tree-total {
		font-size: 0.85rem;
		color: #999;
		font-variant-numeric: tabular-nums;
		white-space: nowrap;
	}
	.tree-row input[type="number"] {
		width: 80px;
		padding: 0.35rem 0.5rem;
		border: 1px solid #ddd;
		border-radius: 4px;
		font-size: 0.9rem;
		text-align: right;
	}
	.tree-row input[type="number"]:focus { outline: none; border-color: #2d6a4f; }
	.edit-table .children-panel {
		border-left: 3px solid #2d6a4f;
		margin-bottom: 0.15rem;
	}

	/* Inline add row */
	.add-row {
		margin-top: 0.25rem;
	}
	.add-input-wrap {
		flex: 1;
	}

	/* Savings column: single white card with internal sections */
	.savings-column {
		display: flex;
		flex-direction: column;
		background: white;
		border-radius: 8px;
		padding: 1.25rem;
	}
	.savings-column .section {
		background: none;
		border-radius: 0;
		padding: 0;
		margin-bottom: 1.25rem;
	}
	.savings-column .section:last-of-type {
		margin-bottom: 0;
	}
	.savings-subtotal {
		border-top: 2px solid #e5e7eb;
		padding-top: 0.75rem;
		margin-top: 1.25rem;
	}

	/* Balance badge */
	.balance-badge {
		font-size: 0.75rem;
		color: #2d6a4f;
		background: #ecfdf5;
		padding: 0.15rem 0.4rem;
		border-radius: 4px;
		white-space: nowrap;
		font-variant-numeric: tabular-nums;
		flex-shrink: 0;
		min-width: 5rem;
		text-align: right;
	}

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
		position: relative;
	}
	.bar-fill {
		height: 100%;
		border-radius: 4px;
		transition: width 0.3s;
	}
	.income-bar { background: #16a34a; }
	.expense-bar-ok { background: #2d6a4f; }
	.expense-bar-over { background: #dc2626; }

	/* 4-column variant (fixed bills, sinking funds, saving goals) */
	.bva-table-fixed .bva-header,
	.bva-table-fixed .bva-row,
	.bva-table-fixed a.bva-row-link {
		grid-template-columns: 3fr 1fr 1fr 1fr;
	}
	.check-ok { color: #16a34a; font-size: 1.2rem; font-weight: bold; }
	.check-warn { color: #dc2626; font-size: 1.2rem; font-weight: bold; }
	.balance-text { color: #2d6a4f; font-size: 0.85rem; }

	/* Section subtotals */
	.bva-subtotal {
		border-top: 2px solid #e5e7eb;
		border-bottom: none;
		font-weight: 700;
		padding-top: 0.75rem;
	}

	/* Clickable rows */
	.bva-row-link {
		text-decoration: none;
		color: inherit;
		cursor: pointer;
		border-radius: 4px;
		transition: background-color 0.1s;
	}
	.bva-row-link:hover {
		background-color: #f0fdf4;
	}
	a.bva-row-link {
		display: grid;
		grid-template-columns: 2fr 1fr 1fr 1.2fr 1.5fr;
		padding: 0.6rem 0;
		border-bottom: 1px solid #f0f0f0;
		align-items: center;
	}

	/* BVA tree parent rows */
	.bva-row-parent {
		background: none;
		border: none;
		width: 100%;
		text-align: left;
		cursor: pointer;
		border-radius: 4px;
		font-size: inherit;
		font-weight: 500;
		color: inherit;
	}
	.bva-row-parent:hover { background: #f9fafb; }
	.bva-children {
		border-left: 3px solid #2d6a4f;
		margin-left: 0.5rem;
		margin-bottom: 0.15rem;
	}

	/* Pacing */
	.pace-marker {
		position: absolute;
		top: -2px;
		bottom: -2px;
		width: 2px;
		background: #1a1a1a;
		border-radius: 1px;
		opacity: 0.5;
		pointer-events: none;
	}
	.pace-label {
		font-size: 0.7rem;
		display: block;
		margin-top: 0.15rem;
	}
	.pace-ahead {
		color: #f59e0b;
		font-weight: 600;
	}

	/* Uncategorized section */
	.unmapped-section {
		border-left: 3px solid #f59e0b;
	}
	.unmapped-desc {
		color: #666;
		font-size: 0.85rem;
		margin: 0 0 0.75rem;
	}
	.unmapped-row {
		display: flex;
		justify-content: space-between;
		padding: 0.5rem 0;
		font-size: 0.9rem;
		border-bottom: 1px solid #f0f0f0;
	}
	.unmapped-link {
		display: inline-block;
		margin-top: 0.75rem;
		color: #2d6a4f;
		font-size: 0.85rem;
		text-decoration: none;
	}
	.unmapped-link:hover { text-decoration: underline; }

	/* Responsive */
	@media (max-width: 1200px) {
		.budget-grid {
			grid-template-columns: repeat(2, 1fr);
		}
	}
	@media (max-width: 700px) {
		.budget-grid {
			grid-template-columns: 1fr;
		}
		.bva-header, .bva-row, a.bva-row-link {
			grid-template-columns: 2fr 1fr 1fr 1fr;
		}
		.bva-table-fixed .bva-header,
		.bva-table-fixed .bva-row,
		.bva-table-fixed a.bva-row-link {
			grid-template-columns: 2fr 1fr 1fr 1fr;
		}
		.bar-col { display: none; }
	}
</style>
