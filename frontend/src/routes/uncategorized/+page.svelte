<script lang="ts">
	import { getUncategorized, bulkCategorize, formatEuro, type UncategorizedGroup } from '$lib/api';
	import CategoryInput from '$lib/components/CategoryInput.svelte';

	let groups: UncategorizedGroup[] = $state([]);
	let loading = $state(true);

	// Per-group selected category
	let selections: Record<string, number | null> = $state({});
	let applying: Record<string, boolean> = $state({});
	let applied: Record<string, number> = $state({});

	async function load() {
		loading = true;
		try {
			groups = await getUncategorized();
		} finally {
			loading = false;
		}
	}

	$effect(() => { load(); });

	async function apply(group: UncategorizedGroup) {
		const categoryId = selections[group.bank_category];
		if (categoryId == null) return;
		applying = { ...applying, [group.bank_category]: true };
		try {
			const result = await bulkCategorize({
				bank_category: group.bank_category,
				category_id: categoryId,
				save_mapping: true,
			});
			applied = { ...applied, [group.bank_category]: result.updated };
			groups = groups.filter(g => g.bank_category !== group.bank_category);
		} finally {
			applying = { ...applying, [group.bank_category]: false };
		}
	}

	let total = $derived(groups.reduce((s, g) => s + g.count, 0));
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
		<p class="subtitle">{total} transaction{total !== 1 ? 's' : ''} across {groups.length} bank categories need a category.</p>

		<div class="groups">
			{#each groups as group}
				{@const isApplying = applying[group.bank_category]}
				{@const selectedId = selections[group.bank_category] ?? null}
				<div class="group-row">
					<div class="group-info">
						<span class="bank-cat">{group.bank_category}</span>
						<span class="group-meta">{group.count} transaction{group.count !== 1 ? 's' : ''} &middot; {formatEuro(group.total)}</span>
					</div>
					<div class="group-action">
						<div class="cat-input-wrap">
							<CategoryInput
								value={selectedId}
								onchange={(v) => { selections = { ...selections, [group.bank_category]: v }; }}
								placeholder="Assign category..."
							/>
						</div>
						<button
							class="apply-btn"
							onclick={() => apply(group)}
							disabled={selectedId == null || isApplying}
						>
							{isApplying ? '...' : 'Apply'}
						</button>
					</div>
				</div>
			{/each}
		</div>
	{/if}
</div>

<style>
	.page { max-width: 800px; }
	h1 { margin: 0 0 0.25rem; color: #1a1a1a; }
	.subtitle { margin: 0 0 1.5rem; color: #666; font-size: 0.9rem; }
	.muted { color: #999; font-style: italic; }

	.empty {
		background: white;
		border-radius: 8px;
		padding: 3rem;
		text-align: center;
		color: #666;
	}

	.groups {
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
	}

	.group-row {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 1rem;
		background: white;
		border-radius: 8px;
		padding: 0.75rem 1rem;
	}

	.group-info {
		display: flex;
		flex-direction: column;
		gap: 0.2rem;
		min-width: 0;
	}

	.bank-cat {
		font-weight: 500;
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

	.group-action {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		flex-shrink: 0;
	}

	.cat-input-wrap {
		width: 220px;
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
</style>
