<script lang="ts">
	import { getCategories, createCategory, type Category } from '$lib/api';

	interface FlatCategory {
		id: number;
		label: string; // full path: "Vaste lasten > Huur"
		name: string;  // leaf name: "Huur"
	}

	interface Props {
		value: number | null;
		onchange: (id: number | null) => void;
		placeholder?: string;
	}

	let { value, onchange, placeholder = 'Select category...' }: Props = $props();

	let flatCategories: FlatCategory[] = $state([]);
	let inputValue = $state('');
	let suggestions: FlatCategory[] = $state([]);
	let showDropdown = $state(false);
	let highlightIndex = $state(-1);
	let debounceTimer: ReturnType<typeof setTimeout> | null = null;
	let inputEl: HTMLInputElement | undefined = $state(undefined);
	let containerEl: HTMLDivElement | undefined = $state(undefined);
	let editing = $state(false);

	// Derive the display label from the current value ID
	let currentLabel = $derived(
		value != null ? (flatCategories.find(c => c.id === value)?.label ?? '') : ''
	);

	function buildFlat(cats: Category[], parentLabel = ''): FlatCategory[] {
		let result: FlatCategory[] = [];
		for (const c of cats) {
			const label = parentLabel ? `${parentLabel} > ${c.name}` : c.name;
			result.push({ id: c.id, label, name: c.name });
			if (c.children?.length) {
				result = result.concat(buildFlat(c.children, label));
			}
		}
		return result;
	}

	async function loadCategories() {
		try {
			const cats = await getCategories();
			flatCategories = buildFlat(cats);
		} catch { /* ignore */ }
	}

	let loaded = false;
	$effect(() => {
		if (!loaded) {
			loaded = true;
			loadCategories();
		}
	});

	function selectById(id: number) {
		onchange(id);
		inputValue = '';
		suggestions = [];
		showDropdown = false;
		highlightIndex = -1;
		editing = false;
	}

	function clearValue() {
		onchange(null);
		editing = true;
		setTimeout(() => inputEl?.focus(), 0);
	}

	function startEditing() {
		editing = true;
		inputValue = '';
		setTimeout(() => inputEl?.focus(), 0);
	}

	async function createCategoryPath(path: string): Promise<number | null> {
		const parts = path.split('>').map(s => s.trim()).filter(Boolean);
		if (parts.length === 0) return null;

		try {
			const cats = await getCategories();
			flatCategories = buildFlat(cats);
			let parentId: number | undefined = undefined;

			for (const part of parts) {
				const existing = flatCategories.find(
					c => c.name.toLowerCase() === part.toLowerCase() &&
					(parentId == null
						? c.label === c.name  // root: label equals name
						: flatCategories.find(p => p.id === parentId)?.label === c.label.split(' > ').slice(0, -1).join(' > '))
				);
				if (existing) {
					parentId = existing.id;
				} else {
					const created = await createCategory(part, parentId);
					parentId = created.id;
				}
			}

			// Reload categories after potential creation
			const updated = await getCategories();
			flatCategories = buildFlat(updated);
			return parentId ?? null;
		} catch {
			return null;
		}
	}

	async function selectByName(name: string) {
		const trimmed = name.trim();
		if (!trimmed) return;

		// Check if it's an exact match in flat list
		const exact = flatCategories.find(c => c.label.toLowerCase() === trimmed.toLowerCase() || c.name.toLowerCase() === trimmed.toLowerCase());
		if (exact) {
			selectById(exact.id);
			return;
		}

		// Create the category (potentially a path)
		const newId = await createCategoryPath(trimmed);
		if (newId != null) {
			selectById(newId);
		}
	}

	function fetchSuggestions(query: string) {
		if (!query.trim()) {
			suggestions = [];
			showDropdown = false;
			return;
		}
		const q = query.trim().toLowerCase();
		suggestions = flatCategories
			.filter(c => c.label.toLowerCase().includes(q) || c.name.toLowerCase().includes(q))
			.sort((a, b) => {
				const aStarts = a.name.toLowerCase().startsWith(q) || a.label.toLowerCase().startsWith(q);
				const bStarts = b.name.toLowerCase().startsWith(q) || b.label.toLowerCase().startsWith(q);
				if (aStarts && !bStarts) return -1;
				if (!aStarts && bStarts) return 1;
				return a.label.localeCompare(b.label);
			})
			.slice(0, 20);

		showDropdown = q.length > 0;
		highlightIndex = -1;
	}

	function handleInput() {
		if (debounceTimer) clearTimeout(debounceTimer);
		debounceTimer = setTimeout(() => fetchSuggestions(inputValue), 150);
	}

	function handleKeydown(e: KeyboardEvent) {
		const hasAddNew = inputValue.trim() && !suggestions.some(s => s.label.toLowerCase() === inputValue.trim().toLowerCase() || s.name.toLowerCase() === inputValue.trim().toLowerCase());
		const totalItems = suggestions.length + (hasAddNew ? 1 : 0);

		if (e.key === 'Enter') {
			e.preventDefault();
			if (highlightIndex >= 0 && highlightIndex < suggestions.length) {
				selectById(suggestions[highlightIndex].id);
			} else if (highlightIndex === suggestions.length && hasAddNew) {
				selectByName(inputValue);
			} else if (inputValue.trim()) {
				selectByName(inputValue);
			}
		} else if (e.key === 'ArrowDown') {
			e.preventDefault();
			if (showDropdown && highlightIndex < totalItems - 1) highlightIndex++;
		} else if (e.key === 'ArrowUp') {
			e.preventDefault();
			if (showDropdown && highlightIndex > 0) highlightIndex--;
		} else if (e.key === 'Escape') {
			showDropdown = false;
			highlightIndex = -1;
			if (!value) editing = false;
		} else if (e.key === 'Backspace' && !inputValue && value != null) {
			clearValue();
		}
	}

	function handleBlur() {
		setTimeout(() => {
			if (!containerEl?.contains(document.activeElement)) {
				showDropdown = false;
				if (inputValue.trim()) {
					selectByName(inputValue);
				} else if (!value) {
					editing = false;
				} else {
					editing = false;
				}
			}
		}, 150);
	}

	function handleFocus() {
		if (inputValue.trim()) fetchSuggestions(inputValue);
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
	{#if value != null && currentLabel && !editing}
		<div
			class="tags-area"
			role="button"
			tabindex="0"
			onclick={startEditing}
			onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); startEditing(); } }}
		>
			<span class="tag">
				{#if currentLabel.includes(' > ')}
					{@const parts = currentLabel.split(' > ')}
					<span class="path-parent">{parts.slice(0, -1).join(' > ')}</span>
					<span class="path-sep"> › </span>
					<span class="path-leaf">{parts[parts.length - 1]}</span>
				{:else}
					{currentLabel}
				{/if}
				<button
					type="button"
					class="tag-remove"
					onclick={(e) => { e.stopPropagation(); clearValue(); }}
				>&times;</button>
			</span>
		</div>
	{:else}
		<!-- This wrapper just forwards focus to the actual input; keyboard
		     users can tab directly to the input, so click-only is fine here. -->
		<!-- svelte-ignore a11y_click_events_have_key_events -->
		<!-- svelte-ignore a11y_no_static_element_interactions -->
		<div class="tags-area" onclick={() => inputEl?.focus()}>
			<input
				bind:this={inputEl}
				bind:value={inputValue}
				oninput={handleInput}
				onkeydown={handleKeydown}
				onblur={handleBlur}
				onfocus={handleFocus}
				{placeholder}
				type="text"
				class="tag-input"
			/>
		</div>
	{/if}

	{#if showDropdown}
		{@const hasAddNew = inputValue.trim() && !suggestions.some(s => s.label.toLowerCase() === inputValue.trim().toLowerCase() || s.name.toLowerCase() === inputValue.trim().toLowerCase())}
		<ul class="dropdown">
			{#each suggestions as suggestion, i}
				<li>
					<button
						type="button"
						class="dropdown-item"
						class:highlighted={i === highlightIndex}
						onmousedown={(e) => { e.preventDefault(); selectById(suggestion.id); }}
					>
						{#if suggestion.label.includes(' > ')}
							{@const parts = suggestion.label.split(' > ')}
							<span class="path-parent">{parts.slice(0, -1).join(' > ')}</span>
							<span class="path-sep"> › </span>
							<span class="path-leaf">{parts[parts.length - 1]}</span>
						{:else}
							{suggestion.label}
						{/if}
					</button>
				</li>
			{/each}
			{#if hasAddNew}
				<li>
					<button
						type="button"
						class="dropdown-item add-new"
						class:highlighted={highlightIndex === suggestions.length}
						onmousedown={(e) => { e.preventDefault(); selectByName(inputValue); }}
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
	.tag-remove:hover { opacity: 1; }

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

	.path-parent { color: #999; }
	.path-sep { color: #ccc; }
	.path-leaf { font-weight: 500; }

	.dropdown-item.add-new {
		color: #666;
		border-top: 1px solid #eee;
		font-style: italic;
	}
</style>
