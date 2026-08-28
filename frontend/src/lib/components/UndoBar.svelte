<script lang="ts">
	const AUTO_DISMISS_MS = 10_000;

	interface Props {
		count: number;
		onUndo: () => void | Promise<void>;
		onDismiss: () => void;
		/** Optional parenthetical appended to the message, e.g. "mapping kept". */
		note?: string;
	}

	let { count, onUndo, onDismiss, note }: Props = $props();
	let undoing = $state(false);

	$effect(() => {
		const timer = setTimeout(onDismiss, AUTO_DISMISS_MS);
		return () => clearTimeout(timer);
	});

	async function handleUndo() {
		if (undoing) return;
		undoing = true;
		try {
			await onUndo();
		} finally {
			undoing = false;
		}
	}
</script>

<div class="undo-bar" role="status">
	<span class="undo-message">Applied to {count} transaction{count === 1 ? '' : 's'}{note ? ` (${note})` : ''}</span>
	<button class="undo-btn" onclick={handleUndo} disabled={undoing}>
		{undoing ? 'Undoing...' : 'Undo'}
	</button>
</div>

<style>
	.undo-bar {
		position: sticky;
		top: 0;
		z-index: 6;
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 1rem;
		background: var(--color-text);
		color: white;
		border-radius: var(--radius-md);
		padding: 0.6rem 1rem;
		margin-bottom: 0.75rem;
	}
	.undo-message {
		font-size: 0.85rem;
	}
	.undo-btn {
		padding: 0.3rem 0.9rem;
		background: var(--color-card-bg);
		color: var(--color-text);
		border: none;
		border-radius: var(--radius-sm);
		font-size: 0.8rem;
		font-weight: 600;
		cursor: pointer;
		white-space: nowrap;
	}
	.undo-btn:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}
</style>
