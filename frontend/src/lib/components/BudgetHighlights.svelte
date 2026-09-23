<script lang="ts">
	import { getBudgetHighlights, formatEuro, type BudgetHighlights } from '$lib/api';
	import { extractErrorDetail } from '$lib/errors';
	import ErrorBanner from '$lib/components/ErrorBanner.svelte';

	let { budgetId, spendingLinkSuffix }: { budgetId: number; spendingLinkSuffix: string } = $props();

	let data: BudgetHighlights | null = $state(null);
	let loading = $state(true);
	let error: string | null = $state(null);

	async function load(id: number) {
		loading = true;
		error = null;
		try {
			data = await getBudgetHighlights(id);
		} catch (e) {
			error = extractErrorDetail(e);
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		load(budgetId);
	});

	function incidentalCaption(summary: BudgetHighlights['summary']): string {
		const parts = summary.incidental_by_label.map(
			(l) => `${l.label} ${formatEuro(l.amount)}`
		);
		if (summary.unlabeled_incidental !== 0) {
			parts.push(`unlabeled ${formatEuro(summary.unlabeled_incidental)}`);
		}
		if (parts.length === 0) {
			return `raw net ${formatEuro(summary.raw_net)}`;
		}
		return `raw net ${formatEuro(summary.raw_net)} incl. ${parts.join(', ')}`;
	}
</script>

<div class="highlights">
	<h2>Highlights</h2>

	{#if error}
		<ErrorBanner message={error} />
	{/if}

	{#if loading}
		<p class="muted">Loading highlights...</p>
	{:else if data}
		<div class="header-row">
			<div class="header-main">
				<span class="structural-net">{formatEuro(data.summary.structural_net)}</span>
				{#if !data.closed}
					<span class="in-progress">(period in progress)</span>
				{/if}
			</div>
			<div class="header-caption">{incidentalCaption(data.summary)}</div>
			<div class="header-caption scorecard">
				{data.summary.flexible_within_plan} of {data.summary.flexible_total} flexible categories
				within plan; {data.summary.pots_executed} of {data.summary.pots_planned} savings pots
				executed.
			</div>
		</div>

		{#if data.highlights.length === 0}
			<p class="empty-note">Nothing notable yet.</p>
		{:else}
			<div class="cards">
				{#each data.highlights as highlight (highlight.rule + highlight.title)}
					{#snippet cardBody()}
						<div class="card-title">{highlight.title}</div>
						<div class="card-detail">{highlight.detail}</div>
					{/snippet}
					{#if highlight.category_id !== null}
						<a
							class="card severity-{highlight.severity}"
							href="/spending/category/{highlight.category_id}{spendingLinkSuffix}"
						>
							{@render cardBody()}
						</a>
					{:else}
						<div class="card severity-{highlight.severity}">
							{@render cardBody()}
						</div>
					{/if}
				{/each}
			</div>
		{/if}
	{/if}
</div>

<style>
	.highlights {
		background: var(--color-card-bg);
		padding: 1.5rem;
		border-radius: var(--radius-md);
		margin-bottom: 1.5rem;
	}
	h2 { margin: 0 0 0.75rem; font-size: 1.1rem; }
	.muted { color: var(--color-text-muted); font-size: 0.9rem; }

	.header-row {
		margin-bottom: 1rem;
	}
	.header-main {
		font-weight: 700;
		font-size: 1.1rem;
	}
	.structural-net { font-variant-numeric: tabular-nums; }
	.in-progress {
		font-weight: 400;
		font-size: 0.85rem;
		color: var(--color-text-muted);
		margin-left: 0.5rem;
	}
	.header-caption {
		font-size: 0.8rem;
		color: var(--color-text-faint);
		margin-top: 0.2rem;
	}
	.header-caption.scorecard {
		color: var(--color-text-muted);
	}

	.empty-note {
		font-size: 0.9rem;
		color: var(--color-text-muted);
		margin: 0;
	}

	.cards {
		display: flex;
		flex-direction: column;
		gap: 0.6rem;
	}

	.card {
		display: block;
		border-left: 4px solid var(--color-border);
		border-radius: var(--radius-sm);
		background: var(--color-bg-faint);
		padding: 0.6rem 0.9rem;
		text-decoration: none;
		color: inherit;
	}
	a.card {
		cursor: pointer;
	}
	a.card:hover {
		background: var(--color-bg-subtle);
	}

	.card.severity-good {
		border-left-color: var(--color-accent);
		background: var(--color-warn-bg-green);
	}
	.card.severity-info {
		border-left-color: var(--color-border);
		background: var(--color-bg-faint);
	}
	.card.severity-warn {
		border-left-color: var(--color-amber);
		background: var(--color-warn-bg-amber);
	}

	.card-title {
		font-weight: 600;
		font-size: 0.9rem;
	}
	.card-detail {
		font-size: 0.85rem;
		color: var(--color-text-muted);
		margin-top: 0.15rem;
	}

	@media (max-width: 480px) {
		.cards { gap: 0.5rem; }
		.card {
			width: 100%;
			box-sizing: border-box;
		}
	}
</style>
