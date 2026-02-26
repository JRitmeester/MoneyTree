<script lang="ts">
	import { getLineItemCategories, getCategories, createCategory, type Category } from '$lib/api';

	interface Props {
		value: string;
		onchange: (value: string) => void;
		placeholder?: string;
	}

	let { value, onchange, placeholder = 'Select category...' }: Props = $props();

	let currentValue = $derived(value?.trim() || '');
	let inputValue = $state('');
	let suggestions: string[] = $state([]);
	let showDropdown = $state(false);
	let highlightIndex = $state(-1);
	let debounceTimer: ReturnType<typeof setTimeout> | null = null;
	let inputEl: HTMLInputElement | undefined = $state(undefined);
	let containerEl: HTMLDivElement | undefined = $state(undefined);
	let editing = $state(false);

	// Category tree from the Category table, flattened to "Parent > Child" paths
	let categoryPaths: string[] = $state([]);

	function flattenCategories(cats: Category[], parentPath = ''): string[] {
		let result: string[] = [];
		for (const c of cats) {
			const path = parentPath ? `${parentPath} > ${c.name}` : c.name;
			result.push(path);
			if (c.children?.length) {
				result = result.concat(flattenCategories(c.children, path));
			}
		}
		return result;
	}

	// Load category tree once on mount
	let loaded = false;
	$effect(() => {
		if (!loaded) {
			loaded = true;
			getCategories().then(cats => {
				categoryPaths = flattenCategories(cats);
			}).catch(() => {});
		}
	});

	function selectCategory(cat: string) {
		const trimmed = cat.trim();
		if (!trimmed) return;

		// If tag contains ">", ensure the categories exist in the Category table
		if (trimmed.includes('>')) {
			ensureCategoryPath(trimmed);
		}

		onchange(trimmed);
		inputValue = '';
		suggestions = [];
		showDropdown = false;
		highlightIndex = -1;
		editing = false;
	}

	function clearValue() {
		onchange('');
		editing = true;
		setTimeout(() => inputEl?.focus(), 0);
	}

	function startEditing() {
		editing = true;
		inputValue = '';
		setTimeout(() => inputEl?.focus(), 0);
	}

	async function ensureCategoryPath(path: string) {
		const parts = path.split('>').map(s => s.trim()).filter(Boolean);
		if (parts.length === 0) return;

		try {
			const cats = await getCategories();
			let parentId: number | undefined = undefined;

			for (const part of parts) {
				const existing = findCategory(cats, part, parentId ?? null);
				if (existing) {
					parentId = existing.id;
				} else {
					const created = await createCategory(part, parentId);
					parentId = created.id;
				}
			}

			const updatedCats = await getCategories();
			categoryPaths = flattenCategories(updatedCats);
		} catch {
			// Silently continue
		}
	}

	function findCategory(cats: Category[], name: string, parentId: number | null): Category | null {
		for (const c of cats) {
			if (c.name.toLowerCase() === name.toLowerCase() && c.parent_id === parentId) {
				return c;
			}
			if (c.children?.length) {
				const found = findCategory(c.children, name, parentId);
				if (found) return found;
			}
		}
		return null;
	}

	async function fetchSuggestions(query: string) {
		if (!query.trim()) {
			suggestions = [];
			showDropdown = false;
			return;
		}
		try {
			const q = query.trim().toLowerCase();

			const lineItemTags = await getLineItemCategories(query);

			const matchingPaths = categoryPaths.filter(p =>
				p.toLowerCase().includes(q)
			);

			const all = new Set<string>();
			for (const p of matchingPaths) all.add(p);
			for (const t of lineItemTags) all.add(t);

			suggestions = [...all].sort((a, b) => {
				const aStarts = a.toLowerCase().startsWith(q) || a.split(' > ').pop()!.toLowerCase().startsWith(q);
				const bStarts = b.toLowerCase().startsWith(q) || b.split(' > ').pop()!.toLowerCase().startsWith(q);
				if (aStarts && !bStarts) return -1;
				if (!aStarts && bStarts) return 1;
				return a.localeCompare(b);
			});

			showDropdown = q.length > 0;
			highlightIndex = -1;
		} catch {
			suggestions = [];
			showDropdown = query.trim().length > 0;
		}
	}

	function handleInput() {
		if (debounceTimer) clearTimeout(debounceTimer);
		debounceTimer = setTimeout(() => fetchSuggestions(inputValue), 200);
	}

	function handleKeydown(e: KeyboardEvent) {
		const hasAddNew = inputValue.trim() && !suggestions.some(s => s.toLowerCase() === inputValue.trim().toLowerCase());
		const totalItems = suggestions.length + (hasAddNew ? 1 : 0);

		if (e.key === 'Enter') {
			e.preventDefault();
			if (highlightIndex >= 0 && highlightIndex < suggestions.length) {
				selectCategory(suggestions[highlightIndex]);
			} else if (highlightIndex === suggestions.length && hasAddNew) {
				selectCategory(inputValue);
			} else if (inputValue.trim()) {
				selectCategory(inputValue);
			}
		} else if (e.key === 'ArrowDown') {
			e.preventDefault();
			if (showDropdown && highlightIndex < totalItems - 1) {
				highlightIndex++;
			}
		} else if (e.key === 'ArrowUp') {
			e.preventDefault();
			if (showDropdown && highlightIndex > 0) {
				highlightIndex--;
			}
		} else if (e.key === 'Escape') {
			showDropdown = false;
			highlightIndex = -1;
			if (!currentValue) {
				editing = false;
			}
		} else if (e.key === 'Backspace' && !inputValue && currentValue) {
			clearValue();
		}
	}

	function handleBlur(e: FocusEvent) {
		setTimeout(() => {
			if (!containerEl?.contains(document.activeElement)) {
				showDropdown = false;
				if (inputValue.trim()) {
					selectCategory(inputValue);
				} else if (!currentValue) {
					editing = false;
				} else {
					editing = false;
				}
			}
		}, 150);
	}

	function handleFocus() {
		if (inputValue.trim()) {
			fetchSuggestions(inputValue);
		}
	}

	function formatAddNew(input: string): string {
		const trimmed = input.trim();
		if (trimmed.includes('>')) {
			const parts = trimmed.split('>').map(s => s.trim()).filter(Boolean);
			if (parts.length >= 2) {
				const child = parts[parts.length - 1];
				const parent = parts.slice(0, -1).join(' > ');
				return `Create "${child}" under "${parent}"`;
			}
		}
		return `Add new category: ${trimmed}`;
	}
</script>

<div class="category-input" bind:this={containerEl}>
	{#if currentValue && !editing}
		<div class="tags-area" onclick={startEditing}>
			<span class="tag">
				{currentValue}
				<button
					type="button"
					class="tag-remove"
					onclick={(e) => { e.stopPropagation(); clearValue(); }}
				>&times;</button>
			</span>
		</div>
	{:else}
		<div class="tags-area" onclick={() => inputEl?.focus()}>
			<span class="info-icon" title="Type to search existing categories. Use &quot;>&quot; to create subcategories, e.g. &quot;Hardware Store > Paint&quot;">i</span>
			<input
				bind:this={inputEl}
				bind:value={inputValue}
				oninput={handleInput}
				onkeydown={handleKeydown}
				onblur={handleBlur}
				onfocus={handleFocus}
				placeholder={placeholder}
				type="text"
				class="tag-input"
			/>
		</div>
	{/if}

	{#if showDropdown}
		{@const exactMatch = suggestions.some(s => s.toLowerCase() === inputValue.trim().toLowerCase())}
		<ul class="dropdown">
			{#each suggestions as suggestion, i}
				<li>
					<button
						type="button"
						class="dropdown-item"
						class:highlighted={i === highlightIndex}
						onmousedown={(e) => { e.preventDefault(); selectCategory(suggestion); }}
					>
						{#if suggestion.includes(' > ')}
							{@const parts = suggestion.split(' > ')}
							<span class="path-parent">{parts.slice(0, -1).join(' > ')}</span>
							<span class="path-sep"> &rsaquo; </span>
							<span class="path-leaf">{parts[parts.length - 1]}</span>
						{:else}
							{suggestion}
						{/if}
					</button>
				</li>
			{/each}
			{#if inputValue.trim() && !exactMatch}
				<li>
					<button
						type="button"
						class="dropdown-item add-new"
						class:highlighted={highlightIndex === suggestions.length}
						onmousedown={(e) => { e.preventDefault(); selectCategory(inputValue); }}
					>
						{formatAddNew(inputValue)}
					</button>
				</li>
			{/if}
		</ul>
	{/if}
</div>

<style>
	.category-input {
		position: relative;
		width: 100%;
	}

	.tags-area {
		display: flex;
		flex-wrap: wrap;
		gap: 0.25rem;
		align-items: center;
		padding: 0.25rem 0.4rem;
		border: 1px solid #ddd;
		border-radius: 4px;
		background: white;
		cursor: text;
		min-height: 32px;
	}

	.tags-area:focus-within {
		border-color: #2d6a4f;
		outline: none;
		box-shadow: 0 0 0 2px rgba(45, 106, 79, 0.15);
	}

	.tag {
		display: inline-flex;
		align-items: center;
		gap: 0.2rem;
		padding: 0.1rem 0.4rem;
		background: #f0fdf4;
		color: #2d6a4f;
		border-radius: 4px;
		font-size: 0.8rem;
		white-space: nowrap;
	}

	.tag-remove {
		background: none;
		border: none;
		color: #2d6a4f;
		cursor: pointer;
		font-size: 0.9rem;
		padding: 0;
		line-height: 1;
		opacity: 0.6;
	}
	.tag-remove:hover {
		opacity: 1;
	}

	.info-icon {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 16px;
		height: 16px;
		border-radius: 50%;
		background: #e5e7eb;
		color: #666;
		font-size: 0.65rem;
		font-style: italic;
		font-weight: 700;
		flex-shrink: 0;
		cursor: help;
		user-select: none;
	}

	.tag-input {
		flex: 1;
		min-width: 60px;
		border: none;
		outline: none;
		padding: 0.15rem 0;
		font-size: 0.85rem;
		background: transparent;
	}

	.dropdown {
		position: absolute;
		top: 100%;
		left: 0;
		right: 0;
		margin: 0;
		padding: 0;
		list-style: none;
		background: white;
		border: 1px solid #ddd;
		border-top: none;
		border-radius: 0 0 4px 4px;
		max-height: 200px;
		overflow-y: auto;
		z-index: 100;
		box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1);
	}

	.dropdown-item {
		display: block;
		width: 100%;
		padding: 0.4rem 0.6rem;
		text-align: left;
		background: none;
		border: none;
		cursor: pointer;
		font-size: 0.85rem;
		color: #333;
	}

	.dropdown-item:hover,
	.dropdown-item.highlighted {
		background: #f0fdf4;
		color: #2d6a4f;
	}

	.path-parent {
		color: #999;
	}
	.path-sep {
		color: #ccc;
	}
	.path-leaf {
		font-weight: 500;
	}

	.dropdown-item.add-new {
		color: #666;
		border-top: 1px solid #eee;
		font-style: italic;
	}
</style>
