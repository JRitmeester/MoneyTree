<script lang="ts">
	let { message }: { message: string } = $props();
</script>

<div class="error-banner">{message}</div>

<style>
	.error-banner {
		background: var(--color-warn-bg-red);
		color: var(--color-expense);
		padding: 1rem;
		border-radius: var(--radius-md);
		margin-bottom: 1rem;
		font-size: 0.9rem;
	}
</style>
