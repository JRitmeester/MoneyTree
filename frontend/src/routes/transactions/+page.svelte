<script lang="ts">
	import { page as pageStore } from '$app/state';
	import {
		getTransactions, getBudgets, setTransactionFlags, bulkSetFlags,
		getIncidentalLabels, createIncidentalLabel,
		formatEuro, formatDate,
		type Transaction, type BudgetSummary, type IncidentalLabelSummary, type TransactionFlags
	} from '$lib/api';
	import DateRangeFilter from '$lib/components/DateRangeFilter.svelte';
	import CategoryInput from '$lib/components/CategoryInput.svelte';
	import { applyFlagsToTransactions } from '$lib/transactionFlags';
	import { computeUndoGroups } from '$lib/undo';
	import { extractErrorDetail } from '$lib/errors';
	import UndoBar from '$lib/components/UndoBar.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import ErrorBanner from '$lib/components/ErrorBanner.svelte';
	import { dateRange } from '$lib/stores/dateRange';
	import { get } from 'svelte/store';

	interface FlagsSnapshot {
		is_incidental: boolean;
		incidental_label_id: number | null;
		is_internal_transfer: boolean;
	}

	// URL params override store (for direct links), otherwise use stored range
	const urlParams = new URLSearchParams(pageStore.url.search);
	const initialRange = get(dateRange);

	let transactions: Transaction[] = $state([]);
	let budgetPeriods: BudgetSummary[] = $state([]);
	let total = $state(0);
	let page = $state(1);
	let perPage = $state(50);
	let loading = $state(true);
	let error = $state<string | null>(null);

	const PAGE_SIZE_OPTIONS = [20, 50, 100, 200, 500];

	let search = $state('');
	let categoryFilter: number | null = $state(null);
	let dateFrom = $state(urlParams.get('date_from') ?? initialRange.dateFrom);
	let dateTo = $state(urlParams.get('date_to') ?? initialRange.dateTo);

	let searchTimeout: ReturnType<typeof setTimeout>;

	// Bulk selection
	let selected: Record<number, boolean> = $state({});
	let labels: IncidentalLabelSummary[] = $state([]);
	let labelChoice: number | 'none' | 'new' = $state('none');
	let newLabelName = $state('');
	let bulkBusy = $state(false);
	// Single-slot undo, intentionally last-action-only: a new bulk action replaces
	// whatever undoInfo was showing rather than stacking a history of undos.
	let undoInfo: { id: number; count: number; previous: Map<number, FlagsSnapshot> } | null = $state(null);
	let undoCounter = 0;

	let selectedIds = $derived(Object.entries(selected).filter(([, v]) => v).map(([k]) => Number(k)));
	let allOnPageSelected = $derived(
		transactions.length > 0 && transactions.every((tx) => selected[tx.id])
	);

	async function load() {
		loading = true;
		selected = {};
		try {
			const res = await getTransactions({
				page,
				per_page: perPage,
				search: search || undefined,
				category_id: categoryFilter ?? undefined,
				date_from: dateFrom || undefined,
				date_to: dateTo || undefined
			});
			transactions = res.items;
			total = res.total;
		} finally {
			loading = false;
		}
	}

	function handleSearch(e: Event) {
		const val = (e.target as HTMLInputElement).value;
		search = val;
		clearTimeout(searchTimeout);
		searchTimeout = setTimeout(() => {
			page = 1;
			load();
		}, 300);
	}

	function handleDateChange() {
		page = 1;
		load();
	}

	function applyFilters() {
		page = 1;
		load();
	}

	function nextPage() {
		if (page * perPage < total) {
			page++;
			load();
		}
	}

	function prevPage() {
		if (page > 1) {
			page--;
			load();
		}
	}

	function changePerPage(e: Event) {
		perPage = Number((e.target as HTMLSelectElement).value);
		page = 1;
		load();
	}

	$effect(() => {
		load();
		getBudgets().then(bp => { budgetPeriods = bp; });
		getIncidentalLabels().then(ls => { labels = ls; }).catch(() => { labels = []; });
	});

	let totalPages = $derived(Math.ceil(total / perPage));

	function isNewDate(index: number): boolean {
		if (index === 0) return false;
		return transactions[index].datum !== transactions[index - 1].datum;
	}

	async function toggleIncidental(tx: Transaction) {
		try {
			const updated = await setTransactionFlags(tx.id, { is_incidental: !tx.is_incidental });
			transactions = transactions.map((t) =>
				t.id === tx.id
					? { ...t, is_incidental: updated.is_incidental, incidental_label_id: updated.incidental_label_id }
					: t
			);
		} catch (e: any) {
			error = extractErrorDetail(e);
		}
	}

	function toggleSelect(tx: Transaction) {
		selected = { ...selected, [tx.id]: !selected[tx.id] };
	}

	function toggleSelectAll() {
		if (allOnPageSelected) {
			selected = {};
		} else {
			const next: Record<number, boolean> = {};
			for (const tx of transactions) next[tx.id] = true;
			selected = next;
		}
	}

	async function resolveLabelId(): Promise<number | null> {
		if (labelChoice === 'none') return null;
		if (labelChoice === 'new') {
			const name = newLabelName.trim();
			if (!name) return null;
			const created = await createIncidentalLabel(name);
			labels = [...labels, { ...created, total: 0, count: 0, date_from: null, date_to: null }]
				.sort((a, b) => a.name.localeCompare(b.name));
			labelChoice = created.id;
			newLabelName = '';
			return created.id;
		}
		return labelChoice;
	}

	function snapshotFlags(id: number): FlagsSnapshot | undefined {
		const t = transactions.find((tx) => tx.id === id);
		if (!t) return undefined;
		return {
			is_incidental: t.is_incidental,
			incidental_label_id: t.incidental_label_id,
			is_internal_transfer: t.is_internal_transfer
		};
	}

	async function applyBulk(kind: 'incidental' | 'not-incidental' | 'transfer' | 'not-transfer') {
		if (selectedIds.length === 0 || bulkBusy) return;
		bulkBusy = true;
		error = null;
		const targetIds = [...selectedIds];
		try {
			const flags: TransactionFlags = {};
			if (kind === 'incidental') {
				flags.is_incidental = true;
				const labelId = await resolveLabelId();
				if (labelId != null) flags.incidental_label_id = labelId;
			} else if (kind === 'not-incidental') {
				flags.is_incidental = false;
			} else {
				flags.is_internal_transfer = kind === 'transfer';
			}

			const previous = new Map<number, FlagsSnapshot>();
			for (const id of targetIds) {
				const snapshot = snapshotFlags(id);
				if (snapshot) previous.set(id, snapshot);
			}

			await bulkSetFlags(targetIds, flags);
			transactions = applyFlagsToTransactions(transactions, targetIds, flags);
			selected = {};
			undoInfo = { id: ++undoCounter, count: targetIds.length, previous };
		} catch (e: any) {
			error = extractErrorDetail(e);
		} finally {
			bulkBusy = false;
		}
	}

	async function handleUndoBulk() {
		if (!undoInfo) return;
		const { previous, count } = undoInfo;
		const groups = computeUndoGroups(previous);
		const restoredIds = new Set<number>();
		try {
			for (const group of groups) {
				// group.value always carries all three flag fields (see snapshotFlags), so
				// incidental_label_id is sent explicitly (including null) rather than omitted,
				// which lets the backend distinguish "clear the label" from "leave it alone".
				if (group.ids.length === 1) {
					const [result] = await Promise.allSettled([setTransactionFlags(group.ids[0], group.value)]);
					if (result.status === 'fulfilled') restoredIds.add(group.ids[0]);
				} else {
					const [result] = await Promise.allSettled([bulkSetFlags(group.ids, group.value)]);
					if (result.status === 'fulfilled') {
						for (const id of group.ids) restoredIds.add(id);
					}
				}
			}
			transactions = transactions.map((t) => {
				if (!restoredIds.has(t.id)) return t;
				const snapshot = previous.get(t.id);
				return snapshot ? { ...t, ...snapshot } : t;
			});
			if (restoredIds.size < count) {
				error = `Undo incomplete: ${restoredIds.size} of ${count} restored, refresh to verify`;
			}
		} finally {
			undoInfo = null;
		}
	}

	function labelName(id: number | null): string | null {
		if (id == null) return null;
		return labels.find((l) => l.id === id)?.name ?? null;
	}
</script>

<PageHeader title="Transactions" />

<div class="filters">
	<div class="filter-row">
		<input type="text" placeholder="Search description, merchant, or amount..." value={search} oninput={handleSearch} />
		<div class="category-filter">
			<CategoryInput value={categoryFilter} onchange={(v) => { categoryFilter = v; applyFilters(); }} placeholder="Filter by category..." />
		</div>
	</div>
	<DateRangeFilter bind:dateFrom bind:dateTo onchange={handleDateChange} periods={budgetPeriods} />
</div>

<div class="info">
	{total} transactions found
</div>

{#if error}
	<ErrorBanner message={error} />
{/if}

{#if undoInfo}
	{#key undoInfo.id}
		<UndoBar count={undoInfo.count} onUndo={handleUndoBulk} onDismiss={() => { undoInfo = null; }} />
	{/key}
{/if}

{#if selectedIds.length > 0}
	<div class="bulk-bar">
		<span class="bulk-count">{selectedIds.length} selected</span>
		<div class="bulk-label">
			<select bind:value={labelChoice} aria-label="Incidental label">
				<option value="none">No label</option>
				{#each labels as label (label.id)}
					<option value={label.id}>{label.name}</option>
				{/each}
				<option value="new">+ New label...</option>
			</select>
			{#if labelChoice === 'new'}
				<input placeholder="Label name" bind:value={newLabelName} />
			{/if}
		</div>
		<button class="bulk-btn" disabled={bulkBusy} onclick={() => applyBulk('incidental')}>Mark incidental</button>
		<button class="bulk-btn" disabled={bulkBusy} onclick={() => applyBulk('not-incidental')}>Unmark incidental</button>
		<button class="bulk-btn" disabled={bulkBusy} onclick={() => applyBulk('transfer')}>Mark as transfer</button>
		<button class="bulk-btn" disabled={bulkBusy} onclick={() => applyBulk('not-transfer')}>Unmark transfer</button>
		<button class="bulk-btn clear" disabled={bulkBusy} onclick={() => { selected = {}; }}>Clear</button>
	</div>
{/if}

{#if loading}
	<div class="loading">Loading...</div>
{:else}
	<div class="table-wrap">
		<table>
			<thead>
				<tr>
					<th class="select-col">
						<input
							type="checkbox"
							checked={allOnPageSelected}
							onchange={toggleSelectAll}
							aria-label="Select all transactions on this page"
						/>
					</th>
					<th>Date</th>
					<th>Merchant</th>
					<th>Category</th>
					<th class="amount">Amount</th>
					<th class="receipt-col">Receipt</th>
				</tr>
			</thead>
			<tbody>
				{#each transactions as tx, i}
					<tr class:date-divider={isNewDate(i)} onclick={() => window.location.href = `/transactions/${tx.id}`}>
						<td class="select-col" onclick={(e) => e.stopPropagation()}>
							<input
								type="checkbox"
								checked={!!selected[tx.id]}
								onchange={() => toggleSelect(tx)}
								aria-label="Select transaction"
							/>
						</td>
						<td class="date">{formatDate(tx.datum)}</td>
						<td class="merchant">
							{tx.merchant_name || tx.naam || tx.omschrijving.substring(0, 40)}
						</td>
						<td>
							<span class="badge">{tx.category_name || tx.categorie}</span>
							{#if tx.is_internal_transfer}
								<span class="badge transfer">transfer</span>
							{/if}
							{#if tx.is_incidental}
								<span class="badge incidental">
									{labelName(tx.incidental_label_id) ?? 'incidental'}
								</span>
							{/if}
							{#if tx.bedrag < 0 && tx.offset_total > 0}
								<span class="badge offset" title={`Net after offsets: ${formatEuro(tx.bedrag + tx.offset_total)}`}>
									offset
								</span>
							{/if}
							{#if tx.bedrag > 0 && tx.is_offset_income}
								<span class="badge offset" title="Linked as offset, excluded from income">
									offset
								</span>
							{/if}
							{#if tx.bedrag < 0 && !tx.is_internal_transfer}
								<button
									class="flag-toggle"
									title={tx.is_incidental ? 'Unmark as incidental (one-off)' : 'Mark as incidental (one-off)'}
									aria-label={tx.is_incidental ? 'Unmark as incidental' : 'Mark as incidental'}
									onclick={(e) => { e.stopPropagation(); toggleIncidental(tx); }}
								>{tx.is_incidental ? '★' : '☆'}</button>
							{/if}
						</td>
						<td class="amount" class:positive={tx.bedrag > 0} class:negative={tx.bedrag < 0}>
							{formatEuro(tx.bedrag)}
						</td>
						<td class="receipt-col">{tx.has_receipt ? '✓' : ''}</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>

	<div class="pagination">
		<button onclick={prevPage} disabled={page <= 1}>Previous</button>
		<span>Page {page} of {totalPages}</span>
		<button onclick={nextPage} disabled={page >= totalPages}>Next</button>
		<select class="per-page-select" value={perPage} onchange={changePerPage}>
			{#each PAGE_SIZE_OPTIONS as size}
				<option value={size}>{size} per page</option>
			{/each}
		</select>
	</div>
{/if}

<style>
	.filters {
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
		margin-bottom: 1rem;
	}
	.filter-row {
		display: flex;
		gap: 0.75rem;
		flex-wrap: wrap;
	}
	.filters input {
		padding: 0.5rem 0.75rem;
		border: 1px solid var(--color-border);
		border-radius: var(--radius-sm);
		font-size: 0.9rem;
	}
	.filter-row input[type="text"] {
		flex: 2;
		min-width: 150px;
	}
	.category-filter {
		flex: 1;
		min-width: 150px;
	}
	.info {
		font-size: 0.85rem;
		color: var(--color-text-muted);
		margin-bottom: 0.5rem;
	}
	.loading {
		text-align: center;
		padding: 3rem;
		color: var(--color-text-muted);
	}
	.bulk-bar {
		position: sticky;
		top: 0;
		z-index: 5;
		display: flex;
		align-items: center;
		gap: 0.5rem;
		flex-wrap: wrap;
		background: var(--color-text);
		color: white;
		border-radius: var(--radius-md);
		padding: 0.5rem 0.9rem;
		margin-bottom: 0.75rem;
	}
	.bulk-count {
		font-size: 0.85rem;
		font-weight: 600;
		margin-right: 0.25rem;
	}
	.bulk-label {
		display: flex;
		gap: 0.4rem;
		align-items: center;
	}
	.bulk-label select, .bulk-label input {
		padding: 0.3rem 0.5rem;
		border-radius: var(--radius-sm);
		border: 1px solid #444;
		font-size: 0.8rem;
	}
	.bulk-btn {
		padding: 0.35rem 0.7rem;
		background: var(--color-card-bg);
		color: var(--color-text);
		border: none;
		border-radius: var(--radius-sm);
		font-size: 0.8rem;
		cursor: pointer;
	}
	.bulk-btn:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}
	.bulk-btn.clear {
		background: transparent;
		color: #ccc;
		border: 1px solid #555;
	}
	.select-col {
		width: 36px;
		text-align: center;
	}
	.select-col input {
		cursor: pointer;
	}
	.table-wrap {
		overflow-x: auto;
		background: var(--color-card-bg);
		border-radius: var(--radius-md);
	}
	table {
		width: 100%;
		border-collapse: collapse;
	}
	th {
		text-align: left;
		padding: 0.75rem 1rem;
		border-bottom: 2px solid var(--color-border-light);
		font-size: 0.85rem;
		color: var(--color-text-muted);
		font-weight: 600;
	}
	td {
		padding: 0.625rem 1rem;
		border-bottom: 1px solid var(--color-bg-subtle);
		font-size: 0.9rem;
	}
	tr.date-divider td {
		border-top: 2px solid var(--color-border-light);
	}
	tr:hover {
		background: var(--color-bg-faint);
		cursor: pointer;
	}
	.date {
		white-space: nowrap;
		color: var(--color-text-muted);
	}
	.merchant {
		font-weight: 500;
	}
	.amount {
		text-align: right;
		font-variant-numeric: tabular-nums;
		white-space: nowrap;
	}
	.positive { color: var(--color-income); }
	.negative { color: var(--color-text); }
	.badge {
		display: inline-block;
		padding: 0.15rem 0.5rem;
		background: var(--color-warn-bg-green);
		color: var(--color-accent);
		border-radius: 4px;
		font-size: 0.8rem;
	}
	.receipt-col {
		text-align: center;
		width: 60px;
		color: var(--color-income);
	}
	.badge.transfer {
		background: var(--color-transfer-bg);
		color: var(--color-transfer);
		font-size: 0.65rem;
		border-radius: 4px;
		padding: 0.05rem 0.35rem;
		margin-left: 0.35rem;
	}
	.badge.incidental {
		background: var(--color-warn-bg-amber);
		color: var(--color-amber);
		font-size: 0.65rem;
		border-radius: 4px;
		padding: 0.05rem 0.35rem;
		margin-left: 0.35rem;
	}
	.badge.offset {
		background: #ecfeff;
		color: #0e7490;
		font-size: 0.65rem;
		border-radius: 4px;
		padding: 0.05rem 0.35rem;
		margin-left: 0.35rem;
	}
	.flag-toggle {
		background: none;
		border: none;
		cursor: pointer;
		color: var(--color-amber);
		font-size: 0.9rem;
		margin-left: 0.35rem;
	}
	.pagination {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 1rem;
		margin-top: 1rem;
	}
	.pagination button {
		padding: 0.4rem 1rem;
		background: var(--color-card-bg);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-sm);
		cursor: pointer;
		font-size: 0.85rem;
	}
	.pagination button:disabled {
		opacity: 0.4;
		cursor: not-allowed;
	}
	.pagination span {
		font-size: 0.85rem;
		color: var(--color-text-muted);
	}
	.per-page-select {
		padding: 0.4rem 0.5rem;
		border: 1px solid var(--color-border);
		border-radius: var(--radius-sm);
		font-size: 0.85rem;
		color: var(--color-text-muted);
		margin-left: 0.5rem;
	}
</style>
