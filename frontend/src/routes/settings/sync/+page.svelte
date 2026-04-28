<script lang="ts">
	import {
		downloadSyncExport,
		previewSyncImport,
		commitSyncImport,
		type ImportPreview,
		type ImportResultResponse,
	} from '$lib/api';

	let since = $state('');
	let exporting = $state(false);
	let importFile: File | null = $state(null);
	let preview: ImportPreview | null = $state(null);
	let importResult: ImportResultResponse | null = $state(null);
	let updateDuplicates = $state(false);
	let busy = $state(false);
	let errorMsg = $state<string | null>(null);

	async function handleExport() {
		exporting = true;
		errorMsg = null;
		try {
			const blob = await downloadSyncExport(since || undefined);
			const url = URL.createObjectURL(blob);
			const a = document.createElement('a');
			a.href = url;
			const stamp = new Date().toISOString().replace(/[:.]/g, '-');
			a.download = `moneytree-export-${stamp}.json`;
			a.click();
			URL.revokeObjectURL(url);
		} catch (e) {
			errorMsg = e instanceof Error ? e.message : String(e);
		} finally {
			exporting = false;
		}
	}

	async function handlePreview() {
		if (!importFile) return;
		busy = true;
		errorMsg = null;
		preview = null;
		importResult = null;
		try {
			const res = await previewSyncImport(importFile);
			preview = res.preview;
		} catch (e) {
			errorMsg = e instanceof Error ? e.message : String(e);
		} finally {
			busy = false;
		}
	}

	async function handleCommit() {
		if (!importFile) return;
		if (preview && preview.hard_conflicts.length > 0) return;
		busy = true;
		errorMsg = null;
		try {
			importResult = await commitSyncImport(importFile, updateDuplicates);
			preview = importResult.preview;
		} catch (e) {
			errorMsg = e instanceof Error ? e.message : String(e);
		} finally {
			busy = false;
		}
	}
</script>

<section class="container">
	<h1>Sync</h1>

	<article>
		<h2>Export</h2>
		<p>Download all categories, budgets, mappings, and transactions as a single JSON file.</p>
		<label>
			Only transactions added or edited on or after:
			<input type="date" bind:value={since} />
		</label>
		<button onclick={handleExport} disabled={exporting}>
			{exporting ? 'Exporting...' : 'Download export file'}
		</button>
	</article>

	<article>
		<h2>Import</h2>
		<p>Merge a previous export into this instance. Always preview first.</p>
		<input
			type="file"
			accept="application/json"
			onchange={(e) => {
				const t = e.currentTarget as HTMLInputElement;
				importFile = t.files?.[0] ?? null;
				preview = null;
				importResult = null;
			}}
		/>
		<label>
			<input type="checkbox" bind:checked={updateDuplicates} />
			Overwrite existing transactions' category and merchant when import_hash matches
		</label>
		<div class="row">
			<button onclick={handlePreview} disabled={!importFile || busy}>Preview</button>
			<button
				onclick={handleCommit}
				disabled={!importFile || !preview || busy || (preview?.hard_conflicts.length ?? 0) > 0}
			>
				Apply import
			</button>
		</div>

		{#if errorMsg}
			<p class="error">{errorMsg}</p>
		{/if}

		{#if preview}
			<h3>Preview</h3>
			<ul>
				<li>Categories to add: {preview.will_add_categories}</li>
				<li>Category mappings to add: {preview.will_add_category_mappings}</li>
				<li>Budgets to add: {preview.will_add_budgets}</li>
				<li>Budget lines to add: {preview.will_add_budget_lines}</li>
				<li>Budget lines to update: {preview.will_update_budget_lines}</li>
				<li>Budget templates to add: {preview.will_add_budget_templates}</li>
				<li>Transactions to add: {preview.will_add_transactions}</li>
				<li>
					Transactions to update: {preview.will_update_transactions}
					{#if preview.will_update_transactions > 0 && !updateDuplicates}
						<span class="muted">(toggle "Overwrite" above to apply)</span>
					{/if}
				</li>
				<li>Transactions to skip (dedup): {preview.will_skip_transactions}</li>
				<li>Offsets to add: {preview.will_add_offsets}</li>
			</ul>

			{#if preview.add_categories.length > 0}
				<details>
					<summary>New categories ({preview.will_add_categories})</summary>
					<ul class="detail-list">
						{#each preview.add_categories as name}
							<li>{name}</li>
						{/each}
						{#if preview.will_add_categories > preview.add_categories.length}
							<li class="muted">… and {preview.will_add_categories - preview.add_categories.length} more</li>
						{/if}
					</ul>
				</details>
			{/if}

			{#if preview.add_transactions.length > 0}
				<details>
					<summary>New transactions ({preview.will_add_transactions})</summary>
					<ul class="detail-list">
						{#each preview.add_transactions as t}
							<li>
								<code>{t.datum}</code>
								<strong>{t.bedrag.toFixed(2)}</strong>
								{t.merchant_name ?? t.omschrijving}
							</li>
						{/each}
						{#if preview.will_add_transactions > preview.add_transactions.length}
							<li class="muted">… and {preview.will_add_transactions - preview.add_transactions.length} more</li>
						{/if}
					</ul>
				</details>
			{/if}

			{#if preview.update_transactions.length > 0}
				<details>
					<summary>Transactions with field changes ({preview.will_update_transactions})</summary>
					<ul class="detail-list">
						{#each preview.update_transactions as t}
							<li>
								<code>{t.datum}</code> <strong>{t.bedrag.toFixed(2)}</strong>
								{t.merchant_name ?? t.omschrijving}
								<ul>
									{#if t.old_category_name !== t.new_category_name}
										<li>Category: <s>{t.old_category_name ?? '—'}</s> → {t.new_category_name ?? '—'}</li>
									{/if}
									{#if t.old_merchant_name !== t.new_merchant_name}
										<li>Merchant: <s>{t.old_merchant_name ?? '—'}</s> → {t.new_merchant_name ?? '—'}</li>
									{/if}
								</ul>
							</li>
						{/each}
						{#if preview.will_update_transactions > preview.update_transactions.length}
							<li class="muted">… and {preview.will_update_transactions - preview.update_transactions.length} more</li>
						{/if}
					</ul>
				</details>
			{/if}

			{#if preview.skip_transactions.length > 0}
				<details>
					<summary>Skipped transactions ({preview.will_skip_transactions})</summary>
					<ul class="detail-list">
						{#each preview.skip_transactions as t}
							<li>
								<code>{t.datum}</code>
								<strong>{t.bedrag.toFixed(2)}</strong>
								{t.merchant_name ?? t.omschrijving}
							</li>
						{/each}
						{#if preview.will_skip_transactions > preview.skip_transactions.length}
							<li class="muted">… and {preview.will_skip_transactions - preview.skip_transactions.length} more</li>
						{/if}
					</ul>
				</details>
			{/if}

			{#if preview.hard_conflicts.length > 0}
				<h4>Hard conflicts (must resolve before import)</h4>
				<ul>
					{#each preview.hard_conflicts as c}
						<li class="hard">{c.message}</li>
					{/each}
				</ul>
			{/if}

			{#if preview.soft_conflicts.length > 0}
				<h4>Soft conflicts (resolved automatically)</h4>
				<ul>
					{#each preview.soft_conflicts as c}
						<li>{c.message}</li>
					{/each}
				</ul>
			{/if}
		{/if}

		{#if importResult?.committed}
			<div class="post-import">
				<p class="ok">Import committed successfully.</p>
				{#if importResult.backup_path}
					<div class="backup-info">
						<strong>Backup created before this import:</strong>
						<code class="backup-path">{importResult.backup_path}</code>
						<details>
							<summary>How to restore</summary>
							<p>
								Stop the server, replace the live database file with this backup, and restart:
							</p>
							<pre>docker-compose stop
cp "{importResult.backup_path}" data/moneytree.db
docker-compose start</pre>
							<p class="muted">
								Old backups are kept in <code>data/backups/</code>. The 10 most recent are retained automatically.
							</p>
						</details>
					</div>
				{/if}
			</div>
		{/if}
	</article>
</section>

<style>
	.container { max-width: 720px; padding: 1rem; }
	article { margin-block: 1rem; padding: 1rem; border: 1px solid var(--border, #ddd); border-radius: 8px; }
	.row { display: flex; gap: 0.5rem; margin-block: 0.5rem; }
	.error { color: tomato; }
	.ok { color: seagreen; }
	.hard { color: tomato; }
	.muted { color: #666; font-size: 0.9em; }
	label { display: block; margin-block: 0.5rem; }
	.post-import { margin-top: 1rem; padding: 0.75rem; background: rgba(46, 139, 87, 0.08); border-radius: 6px; }
	.backup-info { margin-top: 0.5rem; }
	.backup-path { display: block; margin-block: 0.25rem; padding: 0.25rem 0.5rem; background: #f4f4f4; word-break: break-all; }
	pre { background: #f4f4f4; padding: 0.5rem; border-radius: 4px; overflow-x: auto; }
	details { margin-block: 0.5rem; }
	summary { cursor: pointer; padding: 0.25rem 0; }
	.detail-list { font-size: 0.9em; max-height: 300px; overflow-y: auto; padding-left: 1.25rem; }
	.detail-list code { background: #f4f4f4; padding: 0 0.25em; border-radius: 2px; }
</style>
