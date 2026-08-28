<script lang="ts">
	import {
		getCategories, createCategory, deleteCategory, updateCategory, mergeCategory,
		getCategoryMappings, getUnmappedCategories, createCategoryMapping, deleteCategoryMapping,
		type Category, type CategoryMapping
	} from '$lib/api';
	import { focusOnMount } from '$lib/actions/focusOnMount';
	import CategoryInput from '$lib/components/CategoryInput.svelte';
	import { extractErrorDetail } from '$lib/errors';
	import ErrorBanner from '$lib/components/ErrorBanner.svelte';

	let categories: Category[] = $state([]);
	let mappings: CategoryMapping[] = $state([]);
	let unmapped: string[] = $state([]);
	let loading = $state(true);
	let error: string | null = $state(null);

	// Mapping state: bank_category -> selected category_id for each unmapped row
	let mappingSelections: Record<string, number | null> = $state({});

	async function load() {
		loading = true;
		try {
			const [cats, maps, unm] = await Promise.all([
				getCategories(),
				getCategoryMappings(),
				getUnmappedCategories(),
			]);
			categories = cats;
			mappings = maps;
			unmapped = unm;
		} catch (e: any) {
			error = e.message;
		} finally {
			loading = false;
		}
	}

	$effect(() => { load(); });

	// Add root category
	let addingRoot = $state(false);
	let newRootName = $state('');
	let newRootType = $state('expense');

	function startAddRoot() {
		addingRoot = true;
		newRootName = '';
		newRootType = 'expense';
	}

	function cancelAddRoot() {
		addingRoot = false;
		newRootName = '';
	}

	async function handleAddRoot() {
		const name = newRootName.trim();
		if (!name) return;
		try {
			await createCategory(name, undefined, newRootType);
			addingRoot = false;
			newRootName = '';
			await load();
		} catch (e: any) {
			error = extractErrorDetail(e);
		}
	}

	function handleRootKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter') handleAddRoot();
		if (e.key === 'Escape') cancelAddRoot();
	}

	// Move to... (re-parent)
	let movingId: number | null = $state(null);
	let moveError: string | null = $state(null);

	function startMove(id: number) {
		movingId = id;
		moveError = null;
	}

	function cancelMove() {
		movingId = null;
		moveError = null;
	}

	function collectDescendantIds(cat: Category): Set<number> {
		const ids = new Set<number>();
		function walk(c: Category) {
			for (const child of c.children) {
				ids.add(child.id);
				walk(child);
			}
		}
		walk(cat);
		return ids;
	}

	async function handleMoveTargetChosen(cat: Category, targetId: number | null) {
		if (targetId === cat.id) {
			moveError = 'A category cannot be moved under itself.';
			return;
		}
		if (targetId != null && collectDescendantIds(cat).has(targetId)) {
			moveError = 'A category cannot be moved under one of its own subcategories.';
			return;
		}
		try {
			await updateCategory(cat.id, { parent_id: targetId });
			movingId = null;
			moveError = null;
			await load();
		} catch (e: any) {
			moveError = extractErrorDetail(e);
		}
	}

	async function handleDelete(id: number) {
		if (!confirm('Delete this category?')) return;
		try {
			await deleteCategory(id);
			await load();
		} catch (e: any) {
			error = extractErrorDetail(e);
		}
	}

	// Merge into...
	let mergingId: number | null = $state(null);

	function startMerge(id: number) {
		mergingId = id;
	}

	function cancelMerge() {
		mergingId = null;
	}

	async function handleMergeTargetChosen(source: Category, targetId: number | null) {
		if (targetId == null) return;
		try {
			const counts = await mergeCategory(source.id, targetId, true);
			const target = userCategories.find((c) => c.id === targetId);
			const targetName = target?.name ?? 'target';
			const confirmed = confirm(
				`Merge '${source.name}' into '${targetName}'? This will move ` +
					`${counts.transactions} transactions, ${counts.line_items} line items, ` +
					`${counts.budget_lines} budget lines, ${counts.budget_templates} budget templates, ` +
					`${counts.category_mappings} category mappings, and ${counts.children} subcategories. ` +
					`This cannot be undone.`
			);
			if (!confirmed) {
				mergingId = null;
				return;
			}
			await mergeCategory(source.id, targetId);
			mergingId = null;
			await load();
		} catch (e: any) {
			error = extractErrorDetail(e);
			mergingId = null;
		}
	}

	// Inline add subcategory
	let addingSubTo: number | null = $state(null);
	let newSubName = $state('');
	let subInputEl: HTMLInputElement | undefined = $state(undefined);

	function startAddSub(parentId: number) {
		addingSubTo = parentId;
		newSubName = '';
		// Focus after DOM updates
		setTimeout(() => subInputEl?.focus(), 0);
	}

	function cancelAddSub() {
		addingSubTo = null;
		newSubName = '';
	}

	async function handleAddSub(parent: Category) {
		if (!newSubName.trim()) return;
		try {
			await createCategory(newSubName.trim(), parent.id, parent.category_type);
			addingSubTo = null;
			newSubName = '';
			await load();
		} catch (e: any) {
			if (e.message?.includes('409')) {
				error = 'This category already exists.';
			} else {
				error = extractErrorDetail(e);
			}
		}
	}

	function handleSubKeydown(e: KeyboardEvent, parent: Category) {
		if (e.key === 'Enter') handleAddSub(parent);
		if (e.key === 'Escape') cancelAddSub();
	}

	// Inline rename
	let editingId: number | null = $state(null);
	let editingName = $state('');

	function startRename(cat: Category) {
		editingId = cat.id;
		editingName = cat.name;
	}

	async function saveRename(cat: Category) {
		const newName = editingName.trim();
		if (!newName || newName === cat.name) {
			editingId = null;
			return;
		}
		try {
			await updateCategory(cat.id, { name: newName });
			editingId = null;
			await load();
		} catch (e: any) {
			error = e.message;
		}
	}

	function handleRenameKeydown(e: KeyboardEvent, cat: Category) {
		if (e.key === 'Enter') saveRename(cat);
		if (e.key === 'Escape') editingId = null;
	}

	async function handleToggleType(cat: Category) {
		const newType = cat.category_type === 'income' ? 'expense' : 'income';
		try {
			await updateCategory(cat.id, { category_type: newType });
			await load();
		} catch (e: any) {
			error = e.message;
		}
	}

	async function handleCreateMapping(bankCat: string) {
		const catId = mappingSelections[bankCat];
		if (!catId) return;
		try {
			await createCategoryMapping({ bank_category: bankCat, category_id: catId });
			mappingSelections[bankCat] = null;
			await load();
		} catch (e: any) {
			error = e.message;
		}
	}

	async function handleDeleteMapping(mappingId: number) {
		try {
			await deleteCategoryMapping(mappingId);
			await load();
		} catch (e: any) {
			error = e.message;
		}
	}

	// Flatten categories for parent selector
	function flatList(cats: Category[], depth = 0): { id: number; name: string; category_type: string; depth: number }[] {
		let result: { id: number; name: string; category_type: string; depth: number }[] = [];
		for (const cat of cats) {
			result.push({ id: cat.id, name: cat.name, category_type: cat.category_type, depth });
			if (cat.children.length > 0) {
				result = result.concat(flatList(cat.children, depth + 1));
			}
		}
		return result;
	}

	// Get non-bank categories for mapping dropdown
	let userCategories = $derived(flatList(categories));
</script>

<div class="page-header">
	<div>
		<h1>Categories</h1>
		<p>Manage spending categories. Bank categories are auto-imported from CSV exports.</p>
	</div>
	<div class="header-actions">
		{#if addingRoot}
			<input
				class="rename-input root-name-input"
				type="text"
				bind:value={newRootName}
				placeholder="Category name..."
				onkeydown={handleRootKeydown}
				use:focusOnMount
			/>
			<select bind:value={newRootType}>
				<option value="expense">Expense</option>
				<option value="income">Income</option>
			</select>
			<button class="add-root-btn" onclick={handleAddRoot}>Save</button>
			<button class="cancel-sub-btn" onclick={cancelAddRoot} title="Cancel">&times;</button>
		{:else}
			<button class="add-root-btn" onclick={startAddRoot}>+ New category</button>
		{/if}
	</div>
</div>

{#if error}
	<ErrorBanner message={error} />
{/if}

{#if loading}
	<div class="loading">Loading...</div>
{:else}
	{#if categories.length === 0}
		<p class="muted">No categories yet. Import a CSV to seed bank categories.</p>
	{:else}
		<div class="tree">
			{#snippet catNode(cat: Category, depth: number)}
				<div class="cat-item" class:top={depth === 0} class:child={depth > 0} style={depth > 0 ? `margin-left: ${depth * 1.5}rem` : ''}>
					<div class="cat-row">
						{#if editingId === cat.id}
							<input
								class="rename-input"
								type="text"
								bind:value={editingName}
								onblur={() => saveRename(cat)}
								onkeydown={(e) => handleRenameKeydown(e, cat)}
								use:focusOnMount
							/>
						{:else}
							<span
								class="cat-name"
								role="button"
								tabindex="0"
								ondblclick={() => startRename(cat)}
								onkeydown={(e) => { if (e.key === 'F2' || e.key === 'Enter') startRename(cat); }}
								title="Double-click to rename"
							>{cat.name}</span>
						{/if}
						<button class="add-sub-btn" onclick={() => startAddSub(cat.id)} title="Add subcategory">+</button>
						<span class="col-type">
							<button
								class="badge type-badge"
								class:income-badge={cat.category_type === 'income'}
								class:expense-badge={cat.category_type === 'expense'}
								onclick={() => handleToggleType(cat)}
								title="Click to toggle type"
							>
								{cat.category_type === 'income' ? 'Income' : 'Expense'}
							</button>
						</span>
						<button class="merge-btn" onclick={() => startMerge(cat.id)}>Merge into...</button>
						<button class="move-btn" onclick={() => startMove(cat.id)}>Move to...</button>
						<span class="col-delete">
							{#if !cat.children.length}
								<button class="del-btn" onclick={() => handleDelete(cat.id)}>Delete</button>
							{/if}
						</span>
					</div>
					{#if mergingId === cat.id}
						<div class="merge-inline">
							<span class="merge-label">Merge "{cat.name}" into:</span>
							<div class="merge-picker">
								<CategoryInput
									value={null}
									onchange={(targetId) => handleMergeTargetChosen(cat, targetId)}
									placeholder="Select target category..."
								/>
							</div>
							<button class="cancel-sub-btn" onclick={cancelMerge} title="Cancel">&times;</button>
						</div>
					{/if}
					{#if movingId === cat.id}
						<div class="move-inline">
							<span class="move-label">Move "{cat.name}" to:</span>
							<div class="move-picker">
								<CategoryInput
									value={null}
									onchange={(targetId) => handleMoveTargetChosen(cat, targetId)}
									placeholder="Select new parent..."
								/>
							</div>
							<button class="root-btn" onclick={() => handleMoveTargetChosen(cat, null)}>Make root category</button>
							<button class="cancel-sub-btn" onclick={cancelMove} title="Cancel">&times;</button>
						</div>
						{#if moveError}
							<div class="move-error">{moveError}</div>
						{/if}
					{/if}
					{#if cat.children.length > 0}
						{#each cat.children as child}
							{@render catNode(child, depth + 1)}
						{/each}
					{/if}
					{#if addingSubTo === cat.id}
						<div class="add-sub-inline">
							<input
								class="rename-input"
								type="text"
								bind:this={subInputEl}
								bind:value={newSubName}
								onkeydown={(e) => handleSubKeydown(e, cat)}
								placeholder="Subcategory name..."
							/>
							<button class="cancel-sub-btn" onclick={cancelAddSub} title="Cancel">&times;</button>
						</div>
					{/if}
				</div>
			{/snippet}

			{#each categories as cat}
				{@render catNode(cat, 0)}
			{/each}
		</div>
	{/if}

	<!-- Bank Category Mappings -->
	<h2 class="mappings-title">Bank Category Mappings</h2>
	<p class="mappings-desc">Map bank categories from your CSV imports to your budget categories.</p>

	{#if unmapped.length > 0}
		<div class="unmapped-banner">
			<strong>Unmapped:</strong> {unmapped.join(', ')}
		</div>
	{/if}

	<div class="mappings-section">
		{#if mappings.length === 0 && unmapped.length === 0}
			<p class="muted">No bank categories found. Import a CSV first.</p>
		{:else}
			<div class="mapping-table">
				<div class="mapping-header">
					<span>Bank Category</span>
					<span>Maps to</span>
					<span>Action</span>
				</div>

				<!-- Existing mappings -->
				{#each mappings as mapping}
					<div class="mapping-row">
						<span class="bank-cat">{mapping.bank_category}</span>
						<span class="mapped-to">{mapping.category_name}</span>
						<button class="del-btn" onclick={() => handleDeleteMapping(mapping.id)}>Remove</button>
					</div>
				{/each}

				<!-- Unmapped categories -->
				{#each unmapped as bankCat}
					<div class="mapping-row unmapped-row">
						<span class="bank-cat">{bankCat}</span>
						<select bind:value={mappingSelections[bankCat]}>
							<option value={null}>— select category —</option>
							{#each userCategories as opt}
								<option value={opt.id}>{'—'.repeat(opt.depth)} {opt.name} ({opt.category_type})</option>
							{/each}
						</select>
						<button
							class="map-btn"
							disabled={!mappingSelections[bankCat]}
							onclick={() => handleCreateMapping(bankCat)}
						>Map</button>
					</div>
				{/each}
			</div>
		{/if}
	</div>
{/if}

<style>
	h1 { color: var(--color-text); }
	.page-header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 1rem;
		flex-wrap: wrap;
	}
	.header-actions {
		display: flex;
		align-items: center;
		gap: 0.4rem;
		flex-shrink: 0;
	}
	.header-actions select {
		padding: 0.35rem 0.5rem;
		border: 1px solid var(--color-border);
		border-radius: 4px;
		font-size: 0.85rem;
	}
	.root-name-input {
		min-width: 180px;
	}
	.add-root-btn {
		padding: 0.4rem 0.9rem;
		background: var(--color-accent);
		color: white;
		border: none;
		border-radius: var(--radius-sm);
		cursor: pointer;
		font-size: 0.85rem;
		font-weight: 500;
		white-space: nowrap;
	}
	.add-root-btn:hover { background: #1b4332; }
	.loading { text-align: center; padding: 3rem; color: var(--color-text-muted); }
	.muted { color: var(--color-text-faint); font-style: italic; }

	.tree {
		background: var(--color-card-bg);
		border-radius: var(--radius-md);
		padding: 1rem;
	}
	.cat-item.top {
		border-bottom: 1px solid var(--color-bg-subtle);
	}
	.cat-item.top:last-child {
		border-bottom: none;
	}
	.cat-item.child {
		border-left: 2px solid var(--color-border-light);
		padding-left: 0.75rem;
	}
	.cat-row {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		padding: 0.6rem 0.5rem;
	}
	.cat-name {
		flex: 1;
		font-weight: 500;
		cursor: default;
	}
	.col-type {
		display: inline-block;
		width: 65px;
		text-align: center;
		flex-shrink: 0;
	}
	.col-delete {
		display: inline-block;
		width: 50px;
		text-align: center;
		flex-shrink: 0;
	}
	.cat-name:hover { text-decoration: underline dotted #ccc; }
	.rename-input {
		flex: 1;
		padding: 0.25rem 0.4rem;
		border: 1px solid var(--color-accent);
		border-radius: 4px;
		font-size: 0.9rem;
		font-weight: 500;
		outline: none;
	}
	.badge {
		padding: 0.1rem 0.5rem;
		border-radius: 4px;
		font-size: 0.75rem;
	}
	.type-badge {
		cursor: pointer;
		border: none;
		font-weight: 500;
	}
	.type-badge:hover { opacity: 0.8; }
	.income-badge {
		background: #dcfce7;
		color: var(--color-income);
	}
	.expense-badge {
		background: var(--color-warn-bg-red);
		color: var(--color-expense);
	}
	.add-sub-btn {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 22px;
		height: 22px;
		padding: 0;
		background: none;
		border: 1px solid transparent;
		border-radius: 4px;
		cursor: pointer;
		font-size: 1rem;
		font-weight: 600;
		color: #9ca3af;
		opacity: 0;
		transition: opacity 0.15s;
	}
	.cat-row:hover .add-sub-btn {
		opacity: 1;
	}
	.add-sub-btn:hover {
		color: var(--color-accent);
		border-color: var(--color-accent);
		background: var(--color-warn-bg-green);
	}
	.add-sub-inline {
		display: flex;
		align-items: center;
		gap: 0.35rem;
		padding: 0.3rem 0.5rem 0.5rem 0.75rem;
		margin-left: 1.5rem;
		border-left: 2px solid var(--color-border-light);
	}
	.cancel-sub-btn {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 22px;
		height: 22px;
		padding: 0;
		background: none;
		border: 1px solid transparent;
		border-radius: 4px;
		cursor: pointer;
		font-size: 1rem;
		font-weight: 600;
		color: #9ca3af;
	}
	.cancel-sub-btn:hover {
		color: var(--color-expense);
		border-color: var(--color-expense);
		background: var(--color-warn-bg-red);
	}
	.del-btn {
		padding: 0.2rem 0.6rem;
		background: var(--color-card-bg);
		border: 1px solid var(--color-expense);
		color: var(--color-expense);
		border-radius: 4px;
		cursor: pointer;
		font-size: 0.75rem;
	}
	.merge-btn {
		padding: 0.2rem 0.6rem;
		background: var(--color-card-bg);
		border: 1px solid var(--color-accent);
		color: var(--color-accent);
		border-radius: 4px;
		cursor: pointer;
		font-size: 0.75rem;
		flex-shrink: 0;
	}
	.merge-inline {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		padding: 0.3rem 0.5rem 0.5rem 0.75rem;
		margin-left: 1.5rem;
		border-left: 2px solid var(--color-border-light);
	}
	.merge-label {
		font-size: 0.85rem;
		color: var(--color-text-muted);
		white-space: nowrap;
	}
	.merge-picker {
		flex: 1;
		max-width: 320px;
	}
	.move-btn {
		padding: 0.2rem 0.6rem;
		background: var(--color-card-bg);
		border: 1px solid var(--color-transfer);
		color: var(--color-transfer);
		border-radius: 4px;
		cursor: pointer;
		font-size: 0.75rem;
		flex-shrink: 0;
	}
	.move-inline {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		padding: 0.3rem 0.5rem 0.5rem 0.75rem;
		margin-left: 1.5rem;
		border-left: 2px solid var(--color-border-light);
	}
	.move-label {
		font-size: 0.85rem;
		color: var(--color-text-muted);
		white-space: nowrap;
	}
	.move-picker {
		flex: 1;
		max-width: 320px;
	}
	.root-btn {
		padding: 0.2rem 0.6rem;
		background: var(--color-card-bg);
		border: 1px solid var(--color-text-faint);
		color: #444;
		border-radius: 4px;
		cursor: pointer;
		font-size: 0.75rem;
		white-space: nowrap;
		flex-shrink: 0;
	}
	.move-error {
		margin: 0 0.5rem 0.5rem 2.25rem;
		font-size: 0.8rem;
		color: var(--color-expense);
	}

	/* Mappings section */
	.mappings-title {
		margin: 2rem 0 0.25rem;
		font-size: 1.1rem;
		color: var(--color-text);
	}
	.mappings-desc {
		color: var(--color-text-muted);
		font-size: 0.9rem;
		margin-bottom: 1rem;
	}

	.unmapped-banner {
		background: #fffbeb;
		border: 1px solid #f59e0b;
		border-radius: var(--radius-md);
		padding: 0.75rem 1rem;
		margin-bottom: 1rem;
		font-size: 0.9rem;
		color: #78350f;
	}

	.mappings-section {
		background: var(--color-card-bg);
		border-radius: var(--radius-md);
		padding: 1rem;
	}

	.mapping-table { font-size: 0.9rem; }
	.mapping-header {
		display: grid;
		grid-template-columns: 1fr 1fr auto;
		padding: 0.5rem 0.5rem;
		border-bottom: 2px solid var(--color-border-light);
		font-weight: 600;
		font-size: 0.8rem;
		color: var(--color-text-muted);
	}
	.mapping-row {
		display: grid;
		grid-template-columns: 1fr 1fr auto;
		padding: 0.6rem 0.5rem;
		border-bottom: 1px solid var(--color-bg-subtle);
		align-items: center;
		gap: 0.5rem;
	}
	.mapping-row.unmapped-row {
		background: #fffbeb;
	}
	.bank-cat { font-weight: 500; }
	.mapped-to { color: var(--color-accent); font-weight: 500; }

	.mapping-row select {
		padding: 0.35rem 0.5rem;
		border: 1px solid var(--color-border);
		border-radius: 4px;
		font-size: 0.85rem;
	}
	.map-btn {
		padding: 0.3rem 0.8rem;
		background: var(--color-accent);
		color: white;
		border: none;
		border-radius: 4px;
		cursor: pointer;
		font-size: 0.8rem;
	}
	.map-btn:disabled { opacity: 0.4; cursor: not-allowed; }
</style>
