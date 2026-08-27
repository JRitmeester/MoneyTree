<script lang="ts">
	import { getUncategorized, categorizeSelected, bulkCategorize, formatEuro, formatDate, type UncategorizedGroup } from '$lib/api';
	import CategoryInput from '$lib/components/CategoryInput.svelte';
	import DateRangeFilter from '$lib/components/DateRangeFilter.svelte';

	let groups: UncategorizedGroup[] = $state([]);
	let loading = $state(true);
	let applying = $state(false);

	let nameQuery = $state('');
	let nameFilter = $state('');
	let descriptionQuery = $state('');
	let showNameSuggestions = $state(false);
	let dateFrom = $state('');
	let dateTo = $state('');
	let selectedIds: Set<number> = $state(new Set());
	let selectedCategoryId: number | null = $state(null);
	let saveMapping = $state(true);

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
			const mappingGroup = fullySelectedGroup;
			if (mappingGroup) {
				await bulkCategorize({
					bank_category: mappingGroup.bank_category,
					category_id: selectedCategoryId,
					save_mapping: saveMapping,
				});
			} else {
				await categorizeSelected({
					transaction_ids: [...selectedIds],
					category_id: selectedCategoryId,
				});
			}
			// Refetch from the server rather than optimistically stripping the applied
			// transactions locally: a bulk-categorize apply can affect transactions beyond
			// the ones selected here (every transaction with that bank category), and it
			// can flip has_mapping on other groups, so only the server's view is accurate.
			await load();
			saveMapping = true;
		} finally {
			applying = false;
		}
	}

	function round(n: number): number {
		return Math.round(n * 100) / 100;
	}

	let allNames = $derived.by(() => {
		const names = new Set<string>();
		for (const g of groups) {
			for (const tx of g.transactions) {
				if (!matchesDateRange(tx) || !matchesDescription(tx)) continue;
				const name = tx.merchant_name || tx.naam;
				if (name) names.add(name);
			}
		}
		return [...names].sort((a, b) => a.localeCompare(b));
	});

	let nameSuggestions = $derived.by(() => {
		const q = nameQuery.trim().toLowerCase();
		if (q === '') return allNames;
		return allNames.filter(n => n.toLowerCase().includes(q));
	});

	function selectName(name: string) {
		nameFilter = name;
		nameQuery = name;
		showNameSuggestions = false;
	}

	function clearNameFilter() {
		nameFilter = '';
		nameQuery = '';
		showNameSuggestions = false;
	}

	function matchesName(tx: { merchant_name?: string | null; naam?: string | null }): boolean {
		if (nameFilter === '') return true;
		const name = tx.merchant_name || tx.naam || '';
		return name === nameFilter;
	}

	function matchesDescription(tx: { omschrijving: string }): boolean {
		const q = descriptionQuery.trim().toLowerCase();
		if (q === '') return true;
		return tx.omschrijving.toLowerCase().includes(q);
	}

	function matchesDateRange(tx: { datum: string }): boolean {
		if (dateFrom && tx.datum < dateFrom) return false;
		if (dateTo && tx.datum > dateTo) return false;
		return true;
	}

	function matchesFilters(tx: { merchant_name?: string | null; naam?: string | null; omschrijving: string; datum: string }): boolean {
		return matchesName(tx) && matchesDescription(tx) && matchesDateRange(tx);
	}

	let filteredGroups = $derived.by(() => {
		const hasFilters = nameFilter !== '' || descriptionQuery.trim() !== '' || dateFrom || dateTo;
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

	// Computed against the UNFILTERED `groups` data, not `filteredGroups`. A user's
	// active date/name/description filter can hide some transactions of a group; if we
	// checked against the filtered view, selecting all currently-visible rows would look
	// like "whole group selected" while the server's bulk-categorize endpoint recategorizes
	// (and maps) every uncategorized transaction with that bank category, including ones
	// the user never saw. So the mapping offer and bulkCategorize path only apply when the
	// selection equals the entire true group.
	let fullySelectedGroup: UncategorizedGroup | null = $derived.by(() => {
		if (selectedIds.size === 0) return null;
		const candidates = groups.filter(g => {
			const groupIds = g.transactions.map(tx => tx.id);
			return groupIds.length > 0 && groupIds.every(id => selectedIds.has(id));
		});
		if (candidates.length !== 1) return null;
		const group = candidates[0];
		if (group.transactions.length !== selectedIds.size) return null;
		return group;
	});
</script>

<div class="page">
	<h1>Uncategorized</h1>

	{#if loading}
		<p class="muted">Loading...</p>
	{:else if groups.length === 0}
		<div class="empty">
			<p>All transactions are categorized.</p>
			<a href="/" class="back">&larr; Back to dashboard</a>
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
				<div class="search-wrap name-search">
					<input
						type="text"
						class="search-input"
						placeholder="Filter by name..."
						bind:value={nameQuery}
						onfocus={() => { showNameSuggestions = true; }}
						onblur={() => { setTimeout(() => { showNameSuggestions = false; }, 150); }}
						oninput={() => { nameFilter = ''; showNameSuggestions = true; }}
					/>
					{#if nameFilter}
						<button class="search-clear" onclick={clearNameFilter}>×</button>
					{/if}
					{#if showNameSuggestions && nameSuggestions.length > 0 && nameFilter === ''}
						<ul class="name-suggestions">
							{#each nameSuggestions as name}
								<li>
									<button onmousedown={() => selectName(name)}>{name}</button>
								</li>
							{/each}
						</ul>
					{/if}
				</div>
				<div class="search-wrap">
					<input
						type="text"
						class="search-input"
						placeholder="Filter by description..."
						bind:value={descriptionQuery}
					/>
					{#if descriptionQuery}
						<button class="search-clear" onclick={() => { descriptionQuery = ''; }}>×</button>
					{/if}
				</div>
			</div>
			<div class="bar-right">
				{#if fullySelectedGroup}
					<label class="map-checkbox">
						<input type="checkbox" bind:checked={saveMapping} />
						Also map "{fullySelectedGroup.bank_category}" to this category for future imports
					</label>
				{/if}
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
							<span class="bank-cat-row">
								<span class="bank-cat">{group.bank_category}</span>
								{#if group.has_mapping}
									<span class="badge mapped-badge" title="Future imports map this bank category automatically">Mapped</span>
								{/if}
							</span>
							<span class="group-meta">{group.count} transaction{group.count !== 1 ? 's' : ''} &middot; {formatEuro(group.total)}</span>
						</div>
					</div>

					<table>
						<thead>
							<tr>
								<th class="check-col"></th>
								<th>Date</th>
								<th>Name</th>
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
									<td class="merchant clickable" onclick={() => window.location.href = `/transactions/${tx.id}`}>{tx.merchant_name || tx.naam || ''}</td>
									<td class="description clickable" onclick={() => window.location.href = `/transactions/${tx.id}`}>{tx.omschrijving}</td>
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

	.back {
		display: inline-block;
		margin-top: 0.75rem;
		color: #2d6a4f;
		text-decoration: none;
		font-size: 0.9rem;
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

	.name-search {
		position: relative;
	}

	.name-suggestions {
		position: absolute;
		top: 100%;
		left: 0;
		right: 0;
		max-height: 200px;
		overflow-y: auto;
		background: white;
		border: 1px solid #d1d5db;
		border-top: none;
		border-radius: 0 0 4px 4px;
		box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1);
		list-style: none;
		margin: 0;
		padding: 0;
		z-index: 20;
	}

	.name-suggestions li button {
		display: block;
		width: 100%;
		padding: 0.35rem 0.5rem;
		border: none;
		background: none;
		text-align: left;
		font-size: 0.85rem;
		cursor: pointer;
	}

	.name-suggestions li button:hover {
		background: #f0f7f4;
	}

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

	.map-checkbox {
		display: flex;
		align-items: center;
		gap: 0.4rem;
		font-size: 0.8rem;
		color: #555;
		cursor: pointer;
		max-width: 260px;
		line-height: 1.2;
	}

	.map-checkbox input {
		width: 14px;
		height: 14px;
		cursor: pointer;
		flex-shrink: 0;
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

	.bank-cat-row {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		min-width: 0;
	}

	.bank-cat {
		font-weight: 600;
		font-size: 0.95rem;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.badge {
		padding: 0.1rem 0.5rem;
		border-radius: 4px;
		font-size: 0.7rem;
		white-space: nowrap;
		flex-shrink: 0;
	}

	.mapped-badge {
		background: #e0f2fe;
		color: #0369a1;
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
		white-space: nowrap;
	}

	.description {
		font-size: 0.8rem;
		color: #666;
		max-width: 300px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.amount {
		text-align: right;
		font-variant-numeric: tabular-nums;
		white-space: nowrap;
		width: 100px;
	}

	.negative { color: #1a1a1a; }
</style>
