<script lang="ts">
	let { text = 'Loading...' }: { text?: string } = $props();
</script>

<div class="loading" role="status" aria-live="polite">
	<span class="spinner" aria-hidden="true"></span>
	<span>{text}</span>
</div>

<style>
	.loading {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 0.6rem;
		padding: 3rem;
		color: var(--color-text-muted);
	}
	.spinner {
		width: 1.1rem;
		height: 1.1rem;
		border: 2px solid var(--color-border-light);
		border-top-color: var(--color-accent);
		border-radius: 50%;
		animation: spin 0.7s linear infinite;
	}
	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}
</style>
