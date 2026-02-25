<script lang="ts">
	import {
		getCategories, createCategory, deleteCategory, updateCategory,
		getCategoryMappings, getUnmappedCategories, createCategoryMapping, deleteCategoryMapping,
		type Category, type CategoryMapping
	} from '$lib/api';

	let categories: Category[] = $state([]);
	let mappings: CategoryMapping[] = $state([]);
	let unmapped: string[] = $state([]);
	let loading = $state(true);
	let error: string | null = $state(null);
	let newCatName = $state('');
	let newCatParentId: number | null = $state(null);
	let newCatType = $state('expense');

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

	async function handleCreate() {
		if (!newCatName.trim()) return;
		try {
			await createCategory(newCatName.trim(), newCatParentId ?? undefined, newCatType);
			newCatName = '';
			newCatParentId = null;
			newCatType = 'expense';
			await load();
		} catch (e: any) {
			error = e.message;
		}
	}

	async function handleDelete(id: number) {
		if (!confirm('Delete this category?')) return;
		try {
			await deleteCategory(id);
			await load();
		} catch (e: any) {
			error = e.message;
		}
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
			await updateCategory(cat.id, { name: newName, category_type: cat.category_type });
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
			await updateCategory(cat.id, { name: cat.name, category_type: newType });
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
	let userCategories = $derived(flatList(categories).filter(c => !categories.find(root =>
		root.is_bank_category && root.id === c.id
	)));
</script>

<h1>Categories</h1>
<p>Manage spending categories. Bank categories are auto-imported from CSV exports.</p>

{#if error}
	<div class="error">{error}</div>
{/if}

<div class="add-form">
	<input type="text" bind:value={newCatName} placeholder="New category name" />
	<select bind:value={newCatParentId}>
		<option value={null}>Top-level</option>
		{#each flatList(categories) as opt}
			<option value={opt.id}>{'—'.repeat(opt.depth)} {opt.name}</option>
		{/each}
	</select>
	<select bind:value={newCatType}>
		<option value="expense">Expense</option>
		<option value="income">Income</option>
	</select>
	<button onclick={handleCreate}>Add</button>
</div>

{#if loading}
	<div class="loading">Loading...</div>
{:else}
	{#if categories.length === 0}
		<p class="muted">No categories yet. Import a CSV to seed bank categories.</p>
	{:else}
		<div class="tree">
			{#each categories as cat}
				<div class="cat-item top">
					<div class="cat-row">
						{#if editingId === cat.id}
							<input
								class="rename-input"
								type="text"
								bind:value={editingName}
								onblur={() => saveRename(cat)}
								onkeydown={(e) => handleRenameKeydown(e, cat)}
								autofocus
							/>
						{:else}
							<span class="cat-name" ondblclick={() => startRename(cat)} title="Double-click to rename">{cat.name}</span>
						{/if}
						<button
							class="badge type-badge"
							class:income-badge={cat.category_type === 'income'}
							class:expense-badge={cat.category_type === 'expense'}
							onclick={() => handleToggleType(cat)}
							title="Click to toggle type"
						>
							{cat.category_type}
						</button>
						{#if cat.is_bank_category}
							<span class="badge bank">Bank</span>
						{/if}
						{#if !cat.children.length}
							<button class="del-btn" onclick={() => handleDelete(cat.id)}>Delete</button>
						{/if}
					</div>
					{#if cat.children.length > 0}
						{#each cat.children as child}
							<div class="cat-item child">
								<div class="cat-row">
									{#if editingId === child.id}
									<input
										class="rename-input"
										type="text"
										bind:value={editingName}
										onblur={() => saveRename(child)}
										onkeydown={(e) => handleRenameKeydown(e, child)}
										autofocus
									/>
								{:else}
									<span class="cat-name" ondblclick={() => startRename(child)} title="Double-click to rename">{child.name}</span>
								{/if}
									<button
										class="badge type-badge"
										class:income-badge={child.category_type === 'income'}
										class:expense-badge={child.category_type === 'expense'}
										onclick={() => handleToggleType(child)}
										title="Click to toggle type"
									>
										{child.category_type}
									</button>
									{#if child.is_bank_category}
										<span class="badge bank">Bank</span>
									{/if}
									{#if !child.children.length}
										<button class="del-btn" onclick={() => handleDelete(child.id)}>Delete</button>
									{/if}
								</div>
							</div>
						{/each}
					{/if}
				</div>
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
	h1 { color: #1a1a1a; }
	.error {
		padding: 1rem;
		background: #fef2f2;
		color: #dc2626;
		border-radius: 8px;
		margin: 1rem 0;
	}
	.loading { text-align: center; padding: 3rem; color: #666; }
	.muted { color: #999; font-style: italic; }

	.add-form {
		display: flex;
		gap: 0.5rem;
		align-items: center;
		background: white;
		padding: 1rem;
		border-radius: 8px;
		margin-bottom: 1.5rem;
		flex-wrap: wrap;
	}
	.add-form input, .add-form select {
		padding: 0.5rem;
		border: 1px solid #ddd;
		border-radius: 6px;
		font-size: 0.9rem;
	}
	.add-form input { flex: 1; min-width: 150px; }
	.add-form button {
		padding: 0.5rem 1.25rem;
		background: #2d6a4f;
		color: white;
		border: none;
		border-radius: 6px;
		cursor: pointer;
		font-size: 0.9rem;
	}

	.tree {
		background: white;
		border-radius: 8px;
		padding: 1rem;
	}
	.cat-item.top {
		border-bottom: 1px solid #f0f0f0;
	}
	.cat-item.top:last-child {
		border-bottom: none;
	}
	.cat-item.child {
		margin-left: 1.5rem;
		border-left: 2px solid #e5e7eb;
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
	.cat-name:hover { text-decoration: underline dotted #ccc; }
	.rename-input {
		flex: 1;
		padding: 0.25rem 0.4rem;
		border: 1px solid #2d6a4f;
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
	.badge.bank {
		background: #dbeafe;
		color: #1d4ed8;
	}
	.type-badge {
		cursor: pointer;
		border: none;
		font-weight: 500;
	}
	.type-badge:hover { opacity: 0.8; }
	.income-badge {
		background: #dcfce7;
		color: #16a34a;
	}
	.expense-badge {
		background: #fef2f2;
		color: #dc2626;
	}
	.del-btn {
		padding: 0.2rem 0.6rem;
		background: white;
		border: 1px solid #dc2626;
		color: #dc2626;
		border-radius: 4px;
		cursor: pointer;
		font-size: 0.75rem;
	}

	/* Mappings section */
	.mappings-title {
		margin: 2rem 0 0.25rem;
		font-size: 1.1rem;
		color: #1a1a1a;
	}
	.mappings-desc {
		color: #666;
		font-size: 0.9rem;
		margin-bottom: 1rem;
	}

	.unmapped-banner {
		background: #fffbeb;
		border: 1px solid #f59e0b;
		border-radius: 8px;
		padding: 0.75rem 1rem;
		margin-bottom: 1rem;
		font-size: 0.9rem;
		color: #78350f;
	}

	.mappings-section {
		background: white;
		border-radius: 8px;
		padding: 1rem;
	}

	.mapping-table { font-size: 0.9rem; }
	.mapping-header {
		display: grid;
		grid-template-columns: 1fr 1fr auto;
		padding: 0.5rem 0.5rem;
		border-bottom: 2px solid #e5e7eb;
		font-weight: 600;
		font-size: 0.8rem;
		color: #666;
	}
	.mapping-row {
		display: grid;
		grid-template-columns: 1fr 1fr auto;
		padding: 0.6rem 0.5rem;
		border-bottom: 1px solid #f0f0f0;
		align-items: center;
		gap: 0.5rem;
	}
	.mapping-row.unmapped-row {
		background: #fffbeb;
	}
	.bank-cat { font-weight: 500; }
	.mapped-to { color: #2d6a4f; font-weight: 500; }

	.mapping-row select {
		padding: 0.35rem 0.5rem;
		border: 1px solid #ddd;
		border-radius: 4px;
		font-size: 0.85rem;
	}
	.map-btn {
		padding: 0.3rem 0.8rem;
		background: #2d6a4f;
		color: white;
		border: none;
		border-radius: 4px;
		cursor: pointer;
		font-size: 0.8rem;
	}
	.map-btn:disabled { opacity: 0.4; cursor: not-allowed; }
</style>
