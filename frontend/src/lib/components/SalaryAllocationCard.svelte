<script lang="ts">
	import {
		getSalaryAllocation, listAllocationBuckets,
		createAllocationBucket, updateAllocationBucket, deleteAllocationBucket,
		reorderAllocationBuckets, formatEuro, getSavingsCapacity,
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
	let structuralCapacity: number | null = $state(null);

	// Sizing guide for the bucket editor: what history says is sustainably
	// available (income minus ALL structural spending, incidentals excluded).
	$effect(() => {
		if (!editMode || structuralCapacity !== null) return;
		getSavingsCapacity(6)
			.then((cap) => (structuralCapacity = cap.trailing_6_structural))
			.catch(() => {});
	});

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
			<div class="waterfall-scroll">
				<table class="waterfall">
					<thead>
						<tr>
							<th class="col-name"></th>
							<th class="col-rule">Rule</th>
							<th class="col-goal">Goal</th>
							<th class="col-amount">Amount</th>
						</tr>
					</thead>
					<tbody>
						<tr class="muted">
							<td class="col-name" colspan="3">Recurring bills pot
								<span class="caption">covers bills until next payday</span>
							</td>
							<td class="col-amount">{formatEuro(allocation.bills_pot)}</td>
						</tr>
						{#if allocation.kept_in_checking > 0}
							<tr class="muted">
								<td class="col-name" colspan="3">Kept in checking for imminent bills</td>
								<td class="col-amount">{formatEuro(allocation.kept_in_checking)}</td>
							</tr>
						{/if}
						<tr class="subtotal">
							<td class="col-name" colspan="3">Left to allocate
								<span class="caption">salary minus the rows above</span>
							</td>
							<td class="col-amount">
								{formatEuro(Math.max(0, (allocation.salary_amount ?? 0) - allocation.bills_pot - allocation.kept_in_checking))}
							</td>
						</tr>
						{#each allocation.lines as line (line.bucket_id)}
							<tr class:shortfall={line.shortfall}>
								<td class="col-name">
									{line.name}
									{#if line.shortfall}
										<span class="shortfall-note">not fully funded</span>
									{/if}
								</td>
								<td class="col-rule">{line.rule_type === 'fixed' ? '€ fixed' : `${line.value}%`}</td>
								<td class="col-goal">{line.category_name ?? '—'}</td>
								<td class="col-amount">{formatEuro(line.amount)}</td>
							</tr>
						{/each}
						<tr class="total">
							<td class="col-name" colspan="3">Free to spend</td>
							<td class="col-amount">{formatEuro(allocation.free_to_spend)}</td>
						</tr>
					</tbody>
				</table>
			</div>

			{#if buckets.length === 0}
				<p class="empty-note">
					Divide the "left to allocate" amount deliberately: send fixed amounts
					or percentages of it to savings goals, investing, or anything else,
					and see what is genuinely free to spend.
				</p>
				<button class="add-first" onclick={() => { editMode = true; showDraft = true; }}>
					Add your first bucket
				</button>
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
			{#if structuralCapacity !== null}
				{@const bucketTotal = buckets.filter((b) => b.is_active && b.rule_type === 'fixed').reduce((sum, b) => sum + b.value, 0)}
				<p class="sizing-guide" class:over={bucketTotal > Math.max(0, structuralCapacity)}>
					Sizing guide: over the last 6 months, about
					<strong>{formatEuro(Math.max(0, structuralCapacity))}</strong>/month was
					structurally free after all spending. Your fixed buckets total
					<strong>{formatEuro(bucketTotal)}</strong>; keeping that at or below the
					free amount makes the plan sustainable.
				</p>
			{/if}
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

	.waterfall-scroll { overflow-x: auto; }
	.waterfall {
		width: 100%;
		border-collapse: collapse;
		font-size: 0.95rem;
	}
	.waterfall th {
		font-size: 0.7rem;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--color-text-faint);
		text-align: left;
		padding: 0 0.75rem 0.35rem 0;
	}
	.waterfall th.col-amount { text-align: right; padding-right: 0; }
	.waterfall td {
		padding: 0.45rem 0.75rem 0.45rem 0;
		border-bottom: 1px solid #f0f0f0;
		vertical-align: baseline;
	}
	.col-rule, .col-goal {
		font-size: 0.85rem;
		color: var(--color-text-muted);
		white-space: nowrap;
	}
	td.col-goal { white-space: normal; }
	.col-amount {
		text-align: right;
		white-space: nowrap;
		font-variant-numeric: tabular-nums;
		padding-right: 0;
	}
	tr.muted td { color: var(--color-text-muted); }
	tr.total td { border-bottom: none; font-weight: 700; }
	tr.subtotal td {
		font-weight: 600;
		border-top: 2px solid var(--color-border);
		background: var(--color-warn-bg-green, #f0fdf4);
	}
	tr.shortfall td { background: var(--color-warn-bg-amber); }
	.caption { font-size: 0.75rem; color: var(--color-text-faint); margin-left: 0.5rem; }
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

	.sizing-guide {
		font-size: 0.85rem;
		color: var(--color-text-muted);
		background: var(--color-warn-bg-green, #f0fdf4);
		border: 1px solid var(--color-accent);
		border-radius: var(--radius-sm);
		padding: 0.6rem 0.9rem;
		margin: 0 0 0.9rem;
		max-width: 46rem;
	}
	.sizing-guide.over {
		background: var(--color-warn-bg-amber);
		border-color: var(--color-amber);
	}
</style>
