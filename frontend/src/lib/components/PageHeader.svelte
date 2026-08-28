<script lang="ts">
	import type { Snippet } from 'svelte';

	let {
		title,
		marginBottom = '1.5rem',
		right
	}: { title: string; marginBottom?: string; right?: Snippet } = $props();
</script>

<div class="page-header" style:margin-bottom={marginBottom}>
	<h1>{title}</h1>
	{#if right}
		<div class="page-header-right">
			{@render right()}
		</div>
	{/if}
</div>

<style>
	.page-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		flex-wrap: wrap;
		gap: 1rem;
	}
	h1 {
		margin: 0;
		color: var(--color-text);
	}
</style>
