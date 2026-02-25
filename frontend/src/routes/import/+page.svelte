<script lang="ts">
	import { importCsv, linkReceipt, formatEuro, type ImportResult, type MatchCandidate } from '$lib/api';

	let file: File | null = $state(null);
	let loading = $state(false);
	let updateDuplicates = $state(false);
	let result: ImportResult | null = $state(null);
	let error: string | null = $state(null);
	let pendingMatches: MatchCandidate[] = $state([]);
	let confirmedCount = $state(0);

	async function handleImport() {
		if (!file) return;
		loading = true;
		error = null;
		result = null;
		pendingMatches = [];
		confirmedCount = 0;
		try {
			result = await importCsv(file, updateDuplicates);
			pendingMatches = [...result.matches.pending_confirmation];
		} catch (e: any) {
			error = e.message;
		} finally {
			loading = false;
		}
	}

	let dragging = $state(false);
	let fileInputEl: HTMLInputElement | undefined = $state(undefined);

	function handleFileChange(e: Event) {
		const input = e.target as HTMLInputElement;
		file = input.files?.[0] ?? null;
	}

	function handleDrop(e: DragEvent) {
		e.preventDefault();
		dragging = false;
		const dropped = e.dataTransfer?.files?.[0];
		if (dropped && dropped.name.endsWith('.csv')) {
			file = dropped;
		}
	}

	function handleDragOver(e: DragEvent) {
		e.preventDefault();
		dragging = true;
	}

	function handleDragLeave() {
		dragging = false;
	}

	async function confirmMatch(match: MatchCandidate) {
		try {
			await linkReceipt(match.receipt_id, match.transaction_id);
			pendingMatches = pendingMatches.filter(m => m.receipt_id !== match.receipt_id);
			confirmedCount++;
		} catch (e: any) {
			error = e.message;
		}
	}

	function rejectMatch(match: MatchCandidate) {
		pendingMatches = pendingMatches.filter(m => m.receipt_id !== match.receipt_id);
	}
</script>

<h1>Import Transactions</h1>

<input type="file" accept=".csv" bind:this={fileInputEl} onchange={handleFileChange} class="file-input-hidden" />

<button
	class="drop-zone"
	class:dragging
	class:has-file={file}
	ondrop={handleDrop}
	ondragover={handleDragOver}
	ondragleave={handleDragLeave}
	onclick={() => fileInputEl?.click()}
>
	{#if file}
		<span class="drop-icon">&#10003;</span>
		<span class="drop-filename">{file.name}</span>
		<span class="drop-hint">Click or drag to replace</span>
	{:else}
		<span class="drop-icon">&#8681;</span>
		<span class="drop-text">Drag your downloaded bank statement here, or click to select it from your computer.</span>
		<span class="drop-hint">Accepts ASN Bank CSV exports</span>
	{/if}
</button>

<div class="import-options">
	<label class="option-label">
		<input type="checkbox" bind:checked={updateDuplicates} />
		<span class="option-text">
			Update existing transactions
			<span class="option-desc">Overwrite previously imported transactions with data from this file</span>
		</span>
	</label>

	<button class="import-btn" onclick={handleImport} disabled={!file || loading}>
		{loading ? 'Importing...' : 'Import'}
	</button>
</div>

{#if error}
	<div class="error">{error}</div>
{/if}

{#if result}
	<div class="result">
		<h2>Import Complete</h2>
		<div class="stats">
			<div class="stat">
				<span class="value">{result.imported}</span>
				<span class="label">Imported</span>
			</div>
			{#if result.updated > 0}
				<div class="stat">
					<span class="value">{result.updated}</span>
					<span class="label">Updated</span>
				</div>
			{/if}
			<div class="stat">
				<span class="value">{result.skipped_duplicates}</span>
				<span class="label">Skipped (duplicates)</span>
			</div>
			<div class="stat">
				<span class="value">{result.matches.auto_linked + confirmedCount}</span>
				<span class="label">Matched receipts</span>
			</div>
		</div>

		{#if pendingMatches.length > 0}
			<h3>Confirm Matches</h3>
			<p>These receipts might match imported transactions. Confirm or reject each:</p>
			{#each pendingMatches as match}
				<div class="match-card">
					<div class="match-info">
						<div class="match-side">
							<div class="match-label">Receipt</div>
							<div class="match-merchant">{match.receipt_merchant ?? 'Unknown'}</div>
							<div class="match-amount">{match.receipt_amount != null ? formatEuro(match.receipt_amount) : '?'}</div>
						</div>
						<div class="match-arrow">&#8596;</div>
						<div class="match-side">
							<div class="match-label">Transaction</div>
							<div class="match-merchant">{match.transaction_merchant ?? 'Unknown'}</div>
							<div class="match-amount">{formatEuro(Math.abs(match.transaction_amount))}</div>
						</div>
					</div>
					<div class="match-footer">
						<span class="confidence">Confidence: {(match.confidence * 100).toFixed(0)}%</span>
						<div class="match-actions">
							<button class="confirm-btn" onclick={() => confirmMatch(match)}>Confirm</button>
							<button class="reject-btn" onclick={() => rejectMatch(match)}>Reject</button>
						</div>
					</div>
				</div>
			{/each}
		{:else if result.matches.pending_confirmation.length > 0}
			<p class="all-resolved">All matches resolved.</p>
		{/if}

		<a href="/transactions" class="link">View transactions &rarr;</a>
	</div>
{/if}

<style>
	h1 { color: #1a1a1a; }

	.file-input-hidden {
		position: absolute;
		width: 0;
		height: 0;
		opacity: 0;
		pointer-events: none;
	}

	.drop-zone {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 0.75rem;
		width: 100%;
		min-height: 220px;
		margin: 1.5rem 0 1rem;
		padding: 2.5rem 2rem;
		background: white;
		border: 2px dashed #ccc;
		border-radius: 12px;
		cursor: pointer;
		transition: all 0.15s;
		text-align: center;
	}
	.drop-zone:hover {
		border-color: #2d6a4f;
		background: #f0fdf4;
	}
	.drop-zone.dragging {
		border-color: #2d6a4f;
		background: #f0fdf4;
		border-style: solid;
	}
	.drop-zone.has-file {
		border-color: #16a34a;
		border-style: solid;
		background: #f0fdf4;
	}
	.drop-icon {
		font-size: 2.5rem;
		color: #999;
		line-height: 1;
	}
	.drop-zone.has-file .drop-icon {
		color: #16a34a;
	}
	.drop-text {
		font-size: 1.05rem;
		color: #444;
		max-width: 360px;
	}
	.drop-filename {
		font-size: 1.05rem;
		font-weight: 600;
		color: #1a1a1a;
	}
	.drop-hint {
		font-size: 0.8rem;
		color: #999;
	}

	.import-options {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 1.5rem;
		margin-bottom: 1.5rem;
		flex-wrap: wrap;
	}
	.option-label {
		display: flex;
		align-items: flex-start;
		gap: 0.6rem;
		cursor: pointer;
		padding: 0.75rem 1rem;
		background: white;
		border-radius: 8px;
		border: 1px solid #e5e7eb;
		flex: 1;
		min-width: 250px;
	}
	.option-label:hover {
		border-color: #2d6a4f;
	}
	.option-label input[type="checkbox"] {
		margin-top: 0.15rem;
		width: 18px;
		height: 18px;
		flex-shrink: 0;
		accent-color: #2d6a4f;
	}
	.option-text {
		display: flex;
		flex-direction: column;
		font-size: 0.95rem;
		font-weight: 500;
		color: #1a1a1a;
	}
	.option-desc {
		font-size: 0.8rem;
		font-weight: 400;
		color: #999;
		margin-top: 0.15rem;
	}
	.import-btn {
		padding: 0.65rem 2rem;
		background: #2d6a4f;
		color: white;
		border: none;
		border-radius: 6px;
		cursor: pointer;
		font-size: 1rem;
		font-weight: 500;
		white-space: nowrap;
	}
	.import-btn:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}
	.import-btn:hover:not(:disabled) {
		background: #1b4332;
	}

	button {
		padding: 0.5rem 1.5rem;
		background: #2d6a4f;
		color: white;
		border: none;
		border-radius: 6px;
		cursor: pointer;
		font-size: 0.95rem;
	}
	button:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	.error {
		padding: 1rem;
		background: #fef2f2;
		color: #dc2626;
		border-radius: 8px;
		margin: 1rem 0;
	}
	.result {
		background: white;
		padding: 1.5rem;
		border-radius: 8px;
		margin-top: 1.5rem;
	}
	.stats {
		display: flex;
		gap: 2rem;
		margin: 1rem 0;
	}
	.stat {
		display: flex;
		flex-direction: column;
		align-items: center;
	}
	.stat .value {
		font-size: 2rem;
		font-weight: 700;
		color: #2d6a4f;
	}
	.stat .label {
		font-size: 0.85rem;
		color: #666;
	}
	h3 { margin-top: 1.5rem; }
	.match-card {
		background: #f9fafb;
		padding: 1rem;
		border-radius: 8px;
		margin: 0.75rem 0;
		border-left: 4px solid #f59e0b;
	}
	.match-info {
		display: flex;
		align-items: center;
		gap: 1rem;
	}
	.match-side {
		flex: 1;
	}
	.match-label {
		font-size: 0.75rem;
		color: #999;
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}
	.match-merchant {
		font-weight: 600;
		font-size: 0.95rem;
	}
	.match-amount {
		color: #666;
		font-size: 0.9rem;
	}
	.match-arrow {
		font-size: 1.25rem;
		color: #999;
	}
	.match-footer {
		display: flex;
		justify-content: space-between;
		align-items: center;
		margin-top: 0.75rem;
		padding-top: 0.75rem;
		border-top: 1px solid #e5e7eb;
	}
	.confidence {
		font-size: 0.85rem;
		color: #666;
	}
	.match-actions {
		display: flex;
		gap: 0.5rem;
	}
	.confirm-btn {
		padding: 0.35rem 1rem;
		background: #16a34a;
		font-size: 0.85rem;
	}
	.reject-btn {
		padding: 0.35rem 1rem;
		background: white;
		color: #666;
		border: 1px solid #ddd;
		font-size: 0.85rem;
	}
	.all-resolved {
		color: #16a34a;
		font-weight: 500;
	}
	.link {
		display: inline-block;
		margin-top: 1rem;
		color: #2d6a4f;
		font-weight: 600;
	}
</style>
