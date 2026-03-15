<script lang="ts">
	import { getUncategorized, categorizeSelected, formatEuro, formatDate, type UncategorizedGroup } from '$lib/api';
	import CategoryInput from '$lib/components/CategoryInput.svelte';
	import DateRangeFilter from '$lib/components/DateRangeFilter.svelte';

	let groups: UncategorizedGroup[] = $state([]);
	let loading = $state(true);
	let applying = $state(false);

	let searchQuery = $state('');
	let dateFrom = $state('');
	let dateTo = $state('');
	let selectedIds: Set<number> = $state(new Set());
	let selectedCategoryId: number | null = $state(null);

	async function load() {
		loading = true;
		try {
			groups = await getUncategorized();
			selectedIds = new Set();
			selectedCategoryId = null;
		} finally {
			loading = false;
		}
	}

	$effect(() => { load(); });

	function toggleTransaction(id: number) {
		const next = new Set(selectedIds);
		if (next.has(id)) {
			next.delete(id);
		} else {
			next.add(id);
		}
		selectedIds = next;
	}

	function toggleGroup(group: UncategorizedGroup) {
		const groupIds = group.transactions.map(tx => tx.id);
		const allSelected = groupIds.every(id => selectedIds.has(id));
		const next = new Set(selectedIds);
		if (allSelected) {
			for (const id of groupIds) next.delete(id);
		} else {
			for (const id of groupIds) next.add(id);
		}
		selectedIds = next;
	}

	function groupCheckState(group: UncategorizedGroup): 'all' | 'some' | 'none' {
		const groupIds = group.transactions.map(tx => tx.id);
		const count = groupIds.filter(id => selectedIds.has(id)).length;
		if (count === 0) return 'none';
		if (count === groupIds.length) return 'all';
		return 'some';
	}

	async function applySelected() {
		if (selectedIds.size === 0 || selectedCategoryId == null) return;
		applying = true;
		try {
			await categorizeSelected({
				transaction_ids: [...selectedIds],
				category_id: selectedCategoryId,
			});
			const removedIds = new Set(selectedIds);
			groups = groups
				.map(g => ({
					...g,
					transactions: g.transactions.filter(tx => !removedIds.has(tx.id)),
					count: g.transactions.filter(tx => !removedIds.has(tx.id)).length,
					total: round(g.transactions.filter(tx => !removedIds.has(tx.id)).reduce((s, tx) => s + Math.abs(tx.bedrag), 0)),
				}))
				.filter(g => g.transactions.length > 0);
			selectedIds = new Set();
			selectedCategoryId = null;
		} finally {
			applying = false;
		}
	}

	function round(n: number): number {
		return Math.round(n * 100) / 100;
	}

	function matchesSearch(tx: { merchant_name?: string | null; naam?: string | null; omschrijving: string }): boolean {
		const q = searchQuery.trim().toLowerCase();
		if (q === '') return true;
		return [tx.merchant_name, tx.naam, tx.omschrijving]
			.filter(Boolean)
			.some(field => (field as string).toLowerCase().includes(q));
	}

	function matchesDateRange(tx: { datum: string }): boolean {
		if (dateFrom && tx.datum < dateFrom) return false;
		if (dateTo && tx.datum > dateTo) return false;
		return true;
	}

	function matchesFilters(tx: { merchant_name?: string | null; naam?: string | null; omschrijving: string; datum: string }): boolean {
		return matchesSearch(tx) && matchesDateRange(tx);
	}

	let filteredGroups = $derived.by(() => {
		const hasFilters = searchQuery.trim() !== '' || dateFrom || dateTo;
		if (!hasFilters) return groups;
		return groups
			.map(g => {
				const filtered = g.transactions.filter(tx => matchesFilters(tx));
				return { ...g, transactions: filtered, count: filtered.length, total: round(filtered.reduce((s, tx) => s + Math.abs(tx.bedrag), 0)) };
			})
			.filter(g => g.transactions.length > 0);
	});

	let totalCount = $derived(filteredGroups.reduce((s, g) => s + g.count, 0));
	let selectedCount = $derived(selectedIds.size);
</script>

<div class="page">
	<h1>Uncategorized</h1>

	{#if loading}
		<p class="muted">Loading...</p>
	{:else if groups.length === 0}
		<div class="empty">
			<p>All transactions are categorized.</p>
		</div>
	{:else}
		<div class="date-filter-row">
			<DateRangeFilter
				bind:dateFrom
				bind:dateTo
				onchange={() => {}}
			/>
		</div>

		<div class="sticky-bar">
			<div class="bar-left">
				<span class="selected-count">{selectedCount} selected</span>
				<div class="search-wrap">
					<input
						type="text"
						class="search-input"
						placeholder="Filter descriptions..."
						bind:value={searchQuery}
					/>
					{#if searchQuery}
						<button class="search-clear" onclick={() => { searchQuery = ''; }}>×</button>
					{/if}
				</div>
			</div>
			<div class="bar-right">
				<div class="cat-input-wrap">
					<CategoryInput
						value={selectedCategoryId}
						onchange={(v) => { selectedCategoryId = v; }}
						placeholder="Assign category..."
					/>
				</div>
				<button
					class="apply-btn"
					onclick={applySelected}
					disabled={selectedCount === 0 || selectedCategoryId == null || applying}
				>
					{applying ? 'Applying...' : 'Apply'}
				</button>
			</div>
		</div>

		<p class="subtitle">{totalCount} transaction{totalCount !== 1 ? 's' : ''} across {filteredGroups.length} bank categories need a category.</p>

		<div class="groups">
			{#each filteredGroups as group}
				{@const state = groupCheckState(group)}
				<div class="group-card">
					<div class="group-header">
						<label class="group-check">
							<input
								type="checkbox"
								checked={state === 'all'}
								indeterminate={state === 'some'}
								onchange={() => toggleGroup(group)}
							/>
						</label>
						<div class="group-info">
							<span class="bank-cat">{group.bank_category}</span>
							<span class="group-meta">{group.count} transaction{group.count !== 1 ? 's' : ''} &middot; {formatEuro(group.total)}</span>
						</div>
					</div>

					<table>
						<thead>
							<tr>
								<th class="check-col"></th>
								<th>Date</th>
								<th>Description</th>
								<th class="amount">Amount</th>
							</tr>
						</thead>
						<tbody>
							{#each group.transactions as tx}
								<tr>
									<td class="check-col" onclick={(e) => e.stopPropagation()}>
										<input
											type="checkbox"
											checked={selectedIds.has(tx.id)}
											onchange={() => toggleTransaction(tx.id)}
										/>
									</td>
									<td class="date clickable" onclick={() => window.location.href = `/transactions/${tx.id}`}>{formatDate(tx.datum)}</td>
									<td class="merchant clickable" onclick={() => window.location.href = `/transactions/${tx.id}`}>{tx.merchant_name || tx.naam || tx.omschrijving.substring(0, 60)}</td>
									<td class="amount negative clickable" onclick={() => window.location.href = `/transactions/${tx.id}`}>{formatEuro(tx.bedrag)}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{/each}
		</div>
	{/if}
</div>

<style>
	.page { max-width: 900px; }
	h1 { margin: 0 0 0.25rem; color: #1a1a1a; }
	.subtitle { margin: 0 0 1.5rem; color: #666; font-size: 0.9rem; }
	.date-filter-row { margin-bottom: 0.75rem; }
	.muted { color: #999; font-style: italic; }

	.empty {
		background: white;
		border-radius: 8px;
		padding: 3rem;
		text-align: center;
		color: #666;
	}

	.sticky-bar {
		position: sticky;
		top: 0;
		z-index: 10;
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 1rem;
		padding: 0.75rem 1rem;
		margin-bottom: 1rem;
		background: white;
		border-radius: 8px;
		box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
	}

	.bar-left {
		display: flex;
		align-items: center;
		gap: 0.75rem;
	}

	.search-wrap {
		position: relative;
		display: flex;
		align-items: center;
	}

	.search-input {
		padding: 0.3rem 1.8rem 0.3rem 0.5rem;
		border: 1px solid #d1d5db;
		border-radius: 4px;
		font-size: 0.85rem;
		width: 180px;
	}
	.search-input:focus {
		outline: none;
		border-color: #2d6a4f;
		box-shadow: 0 0 0 2px rgba(45, 106, 79, 0.15);
	}

	.search-clear {
		position: absolute;
		right: 4px;
		background: none;
		border: none;
		cursor: pointer;
		font-size: 1.1rem;
		color: #999;
		padding: 0 4px;
		line-height: 1;
	}
	.search-clear:hover { color: #333; }

	.selected-count {
		font-weight: 600;
		font-size: 0.9rem;
		color: #333;
		white-space: nowrap;
	}

	.bar-right {
		display: flex;
		align-items: center;
		gap: 0.5rem;
	}

	.cat-input-wrap {
		width: 250px;
	}

	.apply-btn {
		padding: 0.35rem 0.9rem;
		background: #2d6a4f;
		color: white;
		border: none;
		border-radius: 4px;
		cursor: pointer;
		font-size: 0.85rem;
		white-space: nowrap;
	}
	.apply-btn:hover { background: #1b4332; }
	.apply-btn:disabled { opacity: 0.5; cursor: not-allowed; }

	.groups {
		display: flex;
		flex-direction: column;
		gap: 1rem;
	}

	.group-card {
		background: white;
		border-radius: 8px;
		overflow: hidden;
	}

	.group-header {
		display: flex;
		align-items: center;
		gap: 0.75rem;
		padding: 0.75rem 1rem;
		border-bottom: 2px solid #e5e7eb;
	}

	.group-check {
		display: flex;
		align-items: center;
		cursor: pointer;
		flex-shrink: 0;
	}

	.group-check input {
		width: 16px;
		height: 16px;
		cursor: pointer;
	}

	.group-info {
		display: flex;
		flex-direction: column;
		gap: 0.2rem;
		min-width: 0;
	}

	.bank-cat {
		font-weight: 600;
		font-size: 0.95rem;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.group-meta {
		font-size: 0.8rem;
		color: #999;
		white-space: nowrap;
	}

	table {
		width: 100%;
		border-collapse: collapse;
	}

	th {
		text-align: left;
		padding: 0.5rem 1rem;
		font-size: 0.8rem;
		color: #999;
		font-weight: 500;
		border-bottom: 1px solid #f0f0f0;
	}

	td {
		padding: 0.5rem 1rem;
		border-bottom: 1px solid #f0f0f0;
		font-size: 0.875rem;
	}

	tbody tr:last-child td {
		border-bottom: none;
	}

	tbody tr:hover {
		background: #f9fafb;
	}

	.clickable {
		cursor: pointer;
	}

	.check-col {
		width: 36px;
		text-align: center;
		padding-left: 1rem;
		padding-right: 0;
	}

	.check-col input {
		width: 16px;
		height: 16px;
		cursor: pointer;
	}

	.date {
		white-space: nowrap;
		color: #666;
		width: 90px;
	}

	.merchant {
		font-weight: 500;
	}

	.amount {
		text-align: right;
		font-variant-numeric: tabular-nums;
		white-space: nowrap;
		width: 100px;
	}

	.negative { color: #1a1a1a; }
</style>
