<script lang="ts">
	import {
		getSalaryAllocation, listAllocationBuckets,
		createAllocationBucket, updateAllocationBucket, deleteAllocationBucket,
		reorderAllocationBuckets, formatEuro,
		type SalaryAllocation, type AllocationBucket
	} from '$lib/api';
	import { extractErrorDetail } from '$lib/errors';
	import CategoryInput from '$lib/components/CategoryInput.svelte';

	let allocation: SalaryAllocation | null = $state(null);
	let buckets: AllocationBucket[] = $state([]);
	let loading = $state(true);
	let error: string | null = $state(null);
	let rowErrors: Record<number, string> = $state({});
	let editMode = $state(false);

	let draftName = $state('');
	let draftRuleType: 'fixed' | 'percent' = $state('fixed');
	let draftValue: number | null = $state(null);
	let draftCategoryId: number | null = $state(null);
	let showDraft = $state(false);

	async function load() {
		try {
			const [allocationResult, bucketsResult] = await Promise.all([
				getSalaryAllocation(),
				listAllocationBuckets()
			]);
			allocation = allocationResult;
			buckets = bucketsResult;
			error = null;
		} catch (e) {
			error = extractErrorDetail(e);
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		load();
	});

	function fmtDate(iso: string): string {
		return new Date(iso).toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' });
	}

	function ruleCaption(line: { rule_type: string; value: number }): string {
		return line.rule_type === 'fixed' ? 'fixed' : `${line.value}% of remainder`;
	}

	async function saveBucket(bucket: AllocationBucket, patch: Parameters<typeof updateAllocationBucket>[1]) {
		try {
			await updateAllocationBucket(bucket.id, patch);
			rowErrors = { ...rowErrors, [bucket.id]: '' };
			await load();
		} catch (e) {
			rowErrors = { ...rowErrors, [bucket.id]: extractErrorDetail(e) };
			await load();
		}
	}

	async function removeBucket(bucket: AllocationBucket) {
		if (!confirm(`Delete bucket "${bucket.name}"?`)) return;
		try {
			await deleteAllocationBucket(bucket.id);
			await load();
		} catch (e) {
			rowErrors = { ...rowErrors, [bucket.id]: extractErrorDetail(e) };
		}
	}

	async function move(bucket: AllocationBucket, direction: -1 | 1) {
		const ids = buckets.map((b) => b.id);
		const index = ids.indexOf(bucket.id);
		const target = index + direction;
		if (target < 0 || target >= ids.length) return;
		const reordered = [...ids];
		[reordered[index], reordered[target]] = [reordered[target], reordered[index]];
		try {
			await reorderAllocationBuckets(reordered);
			await load();
		} catch (e) {
			rowErrors = { ...rowErrors, [bucket.id]: extractErrorDetail(e) };
		}
	}

	async function saveDraft() {
		if (!draftName.trim() || draftValue === null || draftValue <= 0) return;
		try {
			await createAllocationBucket({
				name: draftName.trim(),
				rule_type: draftRuleType,
				value: draftValue,
				category_id: draftCategoryId
			});
			draftName = '';
			draftValue = null;
			draftCategoryId = null;
			showDraft = false;
			error = null;
			await load();
		} catch (e) {
			error = extractErrorDetail(e);
		}
	}
</script>

{#if !loading && allocation && allocation.salary_confirmed}
	<div class="section allocation-card">
		<div class="card-header">
			<h2>Salary allocation</h2>
			<button class="edit-toggle" onclick={() => (editMode = !editMode)}>
				{editMode ? 'Done' : 'Edit buckets'}
			</button>
		</div>
		<p class="subtitle">
			{#if allocation.basis === 'actual'}
				Salary received {allocation.payday ? fmtDate(allocation.payday) : ''}:
				{formatEuro(allocation.salary_amount ?? 0)}
			{:else}
				Expected salary, not yet received: {formatEuro(allocation.salary_amount ?? 0)}
			{/if}
		</p>

		{#if error}
			<p class="card-error">{error}</p>
		{/if}

		{#if !editMode}
			{#if buckets.length === 0}
				<p class="empty-note">
					Divide each salary deliberately: after the recurring bills pot, send
					fixed amounts or percentages of what remains to savings goals,
					investing, or anything else, and see what is genuinely free to spend.
				</p>
				<button class="add-first" onclick={() => { editMode = true; showDraft = true; }}>
					Add your first bucket
				</button>
			{:else}
				<div class="waterfall">
					<div class="row muted">
						<span class="row-name">Recurring bills pot
							<span class="caption">covers bills until next payday</span>
						</span>
						<span class="row-amount">{formatEuro(allocation.bills_pot)}</span>
					</div>
					{#if allocation.kept_in_checking > 0}
						<div class="row muted">
							<span class="row-name">Kept in checking for imminent bills</span>
							<span class="row-amount">{formatEuro(allocation.kept_in_checking)}</span>
						</div>
					{/if}
					{#each allocation.lines as line (line.bucket_id)}
						<div class="row" class:shortfall={line.shortfall}>
							<span class="row-name">
								{line.name}
								<span class="caption">{ruleCaption(line)}</span>
								{#if line.category_name}
									<span class="caption category">→ {line.category_name}</span>
								{/if}
								{#if line.shortfall}
									<span class="shortfall-note">not fully funded</span>
								{/if}
							</span>
							<span class="row-amount">{formatEuro(line.amount)}</span>
						</div>
					{/each}
					<div class="row total">
						<span class="row-name">Free to spend</span>
						<span class="row-amount">{formatEuro(allocation.free_to_spend)}</span>
					</div>
				</div>
			{/if}

			{#if allocation.warnings.length > 0}
				<div class="warning-box">
					<h3>Heads up</h3>
					<ul class="warning-list">
						{#each allocation.warnings as warning (warning)}
							<li>{warning}</li>
						{/each}
					</ul>
				</div>
			{/if}
		{:else}
			<div class="edit-list">
				{#each buckets as bucket, i (bucket.id)}
					<div class="edit-row" class:paused={!bucket.is_active}>
						<div class="reorder-buttons">
							<button aria-label="Move up" disabled={i === 0} onclick={() => move(bucket, -1)}>▲</button>
							<button aria-label="Move down" disabled={i === buckets.length - 1} onclick={() => move(bucket, 1)}>▼</button>
						</div>
						<input
							class="name-input"
							value={bucket.name}
							onblur={(e) => {
								const name = (e.currentTarget as HTMLInputElement).value.trim();
								if (name && name !== bucket.name) saveBucket(bucket, { name });
							}}
							onkeydown={(e) => { if (e.key === 'Enter') (e.currentTarget as HTMLInputElement).blur(); }}
						/>
						<select
							value={bucket.rule_type}
							onchange={(e) => saveBucket(bucket, { rule_type: (e.currentTarget as HTMLSelectElement).value })}
						>
							<option value="fixed">€ fixed</option>
							<option value="percent">% of remainder</option>
						</select>
						<span class="value-wrap">
							<input
								class="value-input"
								type="number"
								min="0"
								step={bucket.rule_type === 'fixed' ? '10' : '1'}
								value={bucket.value}
								onblur={(e) => {
									const value = Number((e.currentTarget as HTMLInputElement).value);
									if (value !== bucket.value) saveBucket(bucket, { value });
								}}
								onkeydown={(e) => { if (e.key === 'Enter') (e.currentTarget as HTMLInputElement).blur(); }}
							/>
							<span class="unit">{bucket.rule_type === 'fixed' ? '€' : '%'}</span>
						</span>
						<div class="category-wrap">
							<CategoryInput
								value={bucket.category_id}
								onchange={(id) => saveBucket(bucket, { category_id: id })}
								placeholder="Link a goal (optional)"
							/>
						</div>
						<button
							class="pause-button"
							onclick={() => saveBucket(bucket, { is_active: !bucket.is_active })}
						>
							{bucket.is_active ? 'Pause' : 'Resume'}
						</button>
						<button class="delete-button" onclick={() => removeBucket(bucket)}>Delete</button>
						{#if rowErrors[bucket.id]}
							<p class="row-error">{rowErrors[bucket.id]}</p>
						{/if}
					</div>
				{/each}

				{#if showDraft}
					<div class="edit-row draft">
						<div class="reorder-buttons"></div>
						<input class="name-input" placeholder="Bucket name" bind:value={draftName} />
						<select bind:value={draftRuleType}>
							<option value="fixed">€ fixed</option>
							<option value="percent">% of remainder</option>
						</select>
						<span class="value-wrap">
							<input class="value-input" type="number" min="0" placeholder="0" bind:value={draftValue} />
							<span class="unit">{draftRuleType === 'fixed' ? '€' : '%'}</span>
						</span>
						<div class="category-wrap">
							<CategoryInput
								value={draftCategoryId}
								onchange={(id) => (draftCategoryId = id)}
								placeholder="Link a goal (optional)"
							/>
						</div>
						<button class="save-button" onclick={saveDraft}>Add</button>
						<button class="delete-button" onclick={() => (showDraft = false)}>Cancel</button>
					</div>
				{:else}
					<button class="add-bucket" onclick={() => (showDraft = true)}>+ Add bucket</button>
				{/if}
			</div>
		{/if}
	</div>
{/if}

<style>
	.section {
		background: var(--color-card-bg);
		padding: 1.5rem;
		border-radius: var(--radius-md);
		margin-bottom: 1.5rem;
	}
	.card-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
	}
	h2 { margin: 0; font-size: 1.1rem; }
	.subtitle {
		font-size: 0.85rem;
		color: var(--color-text-muted);
		margin: 0.35rem 0 1rem;
	}
	.edit-toggle, .add-bucket, .add-first {
		background: none;
		border: 1px solid var(--color-border);
		border-radius: var(--radius-sm);
		padding: 0.35rem 0.75rem;
		cursor: pointer;
		font-size: 0.85rem;
	}
	.edit-toggle:hover, .add-bucket:hover, .add-first:hover { background: #f5f5f5; }
	.card-error {
		color: var(--color-expense-red, #b91c1c);
		font-size: 0.85rem;
	}
	.empty-note {
		font-size: 0.9rem;
		color: var(--color-text-muted);
		max-width: 46rem;
	}

	.waterfall { display: flex; flex-direction: column; }
	.row {
		display: flex;
		justify-content: space-between;
		align-items: baseline;
		gap: 1rem;
		padding: 0.45rem 0;
		border-bottom: 1px solid #f0f0f0;
		font-size: 0.95rem;
	}
	.row.muted .row-name, .row.muted .row-amount { color: var(--color-text-muted); }
	.row.total { border-bottom: none; font-weight: 700; }
	.row.shortfall { background: var(--color-warn-bg-amber); }
	.row-name { display: flex; align-items: baseline; gap: 0.5rem; flex-wrap: wrap; }
	.row-amount { white-space: nowrap; font-variant-numeric: tabular-nums; }
	.caption { font-size: 0.75rem; color: var(--color-text-faint); }
	.caption.category { color: var(--color-text-muted); }
	.shortfall-note {
		font-size: 0.75rem;
		color: var(--color-amber);
		font-weight: 600;
	}

	.warning-box {
		margin-top: 1.25rem;
		background: var(--color-warn-bg-amber);
		border: 1px solid #facc15;
		border-left: 4px solid var(--color-amber);
		border-radius: var(--radius-sm);
		padding: 0.75rem 1rem;
	}
	.warning-box h3 {
		margin: 0 0 0.5rem;
		font-size: 0.95rem;
		color: var(--color-amber);
	}
	.warning-list {
		list-style: none;
		padding: 0;
		margin: 0;
	}
	.warning-list li { font-size: 0.85rem; line-height: 1.4; }
	.warning-list li + li {
		margin-top: 0.25rem;
		padding-top: 0.25rem;
		border-top: 1px solid #fde68a;
	}

	.edit-list { display: flex; flex-direction: column; gap: 0.6rem; }
	.edit-row {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		flex-wrap: wrap;
	}
	.edit-row.paused { opacity: 0.55; }
	.reorder-buttons {
		display: flex;
		flex-direction: column;
		gap: 0.1rem;
		width: 2rem;
	}
	.reorder-buttons button {
		border: 1px solid var(--color-border);
		background: none;
		border-radius: 3px;
		cursor: pointer;
		font-size: 0.6rem;
		padding: 0.1rem;
	}
	.reorder-buttons button:disabled { opacity: 0.3; cursor: default; }
	.name-input { flex: 1 1 8rem; min-width: 7rem; }
	.name-input, .value-input, select {
		padding: 0.35rem 0.5rem;
		border: 1px solid var(--color-border);
		border-radius: 4px;
		font-size: 0.9rem;
	}
	.value-wrap { display: flex; align-items: center; gap: 0.25rem; }
	.value-input { width: 5.5rem; }
	.unit { color: var(--color-text-muted); font-size: 0.85rem; }
	.category-wrap { flex: 1 1 12rem; min-width: 10rem; }
	.pause-button, .delete-button, .save-button {
		background: none;
		border: 1px solid var(--color-border);
		border-radius: var(--radius-sm);
		padding: 0.3rem 0.6rem;
		cursor: pointer;
		font-size: 0.8rem;
	}
	.delete-button { color: var(--color-expense-red, #b91c1c); }
	.save-button { color: var(--color-accent); font-weight: 600; }
	.row-error {
		flex-basis: 100%;
		margin: 0;
		font-size: 0.8rem;
		color: var(--color-expense-red, #b91c1c);
	}

	@media (max-width: 480px) {
		.reorder-buttons button, .pause-button, .delete-button, .save-button {
			min-height: 44px;
			min-width: 44px;
		}
		.edit-row { row-gap: 0.4rem; }
	}
</style>
