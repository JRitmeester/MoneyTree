<script lang="ts">
	import {
		getRecurringPayments, getRecurringNotices, rescanRecurring,
		confirmRecurring, dismissRecurring, updateRecurring, formatEuro, formatDate,
		type RecurringPayment, type RecurringNotice
	} from '$lib/api';
	import { extractErrorDetail } from '$lib/errors';
	import CategoryInput from '$lib/components/CategoryInput.svelte';

	let suggested: RecurringPayment[] = $state([]);
	let confirmed: RecurringPayment[] = $state([]);
	let dismissed: RecurringPayment[] = $state([]);
	let notices: RecurringNotice[] = $state([]);
	let loading = $state(true);
	let error: string | null = $state(null);
	let rescanning = $state(false);

	// Dismissed section is collapsed by default; its list is fetched lazily
	// the first time it's expanded.
	let dismissedExpanded = $state(false);
	let dismissedLoaded = $state(false);
	let dismissedLoading = $state(false);

	// Suggested rows currently expanded into the confirm form.
	let confirmingId: number | null = $state(null);
	let confirmName = $state('');
	let confirmCategoryId: number | null = $state(null);

	// Confirmed rows currently expanded into the edit form.
	let editingId: number | null = $state(null);
	let editName = $state('');
	let editCategoryId: number | null = $state(null);
	let editExpectedAmount = $state('');

	async function load() {
		loading = true;
		error = null;
		try {
			const [suggestedPayments, confirmedPayments, noticesResult] = await Promise.all([
				getRecurringPayments('suggested'),
				getRecurringPayments('confirmed'),
				getRecurringNotices()
			]);
			suggested = suggestedPayments;
			confirmed = confirmedPayments;
			notices = noticesResult;
			if (dismissedExpanded) {
				await loadDismissed();
			}
		} catch (e) {
			error = extractErrorDetail(e);
		} finally {
			loading = false;
		}
	}

	async function loadDismissed() {
		dismissedLoading = true;
		try {
			dismissed = await getRecurringPayments('dismissed');
			dismissedLoaded = true;
		} catch (e) {
			error = extractErrorDetail(e);
		} finally {
			dismissedLoading = false;
		}
	}

	async function toggleDismissed() {
		dismissedExpanded = !dismissedExpanded;
		if (dismissedExpanded && !dismissedLoaded) {
			await loadDismissed();
		}
	}

	$effect(() => { load(); });

	function cadenceLabel(payment: RecurringPayment): string {
		if (payment.cadence === 'monthly') {
			return payment.expected_day
				? `monthly around the ${ordinal(payment.expected_day)}`
				: 'monthly';
		}
		if (payment.cadence === 'four_weekly') return 'every 4 weeks';
		if (payment.cadence === 'yearly') return 'yearly';
		return payment.cadence;
	}

	function ordinal(n: number): string {
		const suffix = ['th', 'st', 'nd', 'rd'];
		const v = n % 100;
		return n + (suffix[(v - 20) % 10] || suffix[v] || suffix[0]);
	}

	function noticesFor(paymentId: number): RecurringNotice[] {
		return notices.filter(n => n.recurring_payment_id === paymentId);
	}

	// Simple client-side heuristic: the confirmed income row with the largest
	// expected amount is treated as the likely salary and gets a hint.
	let salaryPaymentId = $derived.by(() => {
		const incomeRows = confirmed.filter(p => p.is_income);
		if (incomeRows.length === 0) return null;
		return incomeRows.reduce((max, p) => (p.expected_amount > max.expected_amount ? p : max), incomeRows[0]).id;
	});

	function startConfirm(payment: RecurringPayment) {
		confirmingId = payment.id;
		confirmName = payment.name;
		confirmCategoryId = payment.category_id;
	}

	function cancelConfirm() {
		confirmingId = null;
	}

	async function saveConfirm(paymentId: number) {
		error = null;
		try {
			await confirmRecurring(paymentId, { name: confirmName, category_id: confirmCategoryId });
			confirmingId = null;
			await load();
		} catch (e) {
			error = extractErrorDetail(e);
		}
	}

	// Suggested rows: dismissing a pattern that was never confirmed is a
	// one-click, low-stakes action.
	async function dismissSuggested(paymentId: number) {
		error = null;
		try {
			await dismissRecurring(paymentId);
			await load();
		} catch (e) {
			error = extractErrorDetail(e);
		}
	}

	// Confirmed rows: dismissing an already-confirmed payment stops notices
	// and future matching, so it's guarded behind a confirmation prompt.
	async function stopTracking(payment: RecurringPayment) {
		const ok = window.confirm(
			`Stop tracking "${payment.name}"? Its history is kept but notices and matching stop.`
		);
		if (!ok) return;
		error = null;
		try {
			await dismissRecurring(payment.id);
			await load();
		} catch (e) {
			error = extractErrorDetail(e);
		}
	}

	async function reconfirm(paymentId: number) {
		error = null;
		try {
			await updateRecurring(paymentId, { status: 'confirmed' });
			dismissedLoaded = false;
			await load();
		} catch (e) {
			error = extractErrorDetail(e);
		}
	}

	function startEdit(payment: RecurringPayment) {
		editingId = payment.id;
		editName = payment.name;
		editCategoryId = payment.category_id;
		editExpectedAmount = String(payment.expected_amount);
	}

	function cancelEdit() {
		editingId = null;
	}

	async function saveEdit(paymentId: number) {
		error = null;
		const amount = Number(editExpectedAmount);
		if (Number.isNaN(amount)) {
			error = 'Expected amount must be a number.';
			return;
		}
		try {
			await updateRecurring(paymentId, {
				name: editName,
				category_id: editCategoryId,
				expected_amount: amount
			});
			editingId = null;
			await load();
		} catch (e) {
			error = extractErrorDetail(e);
		}
	}

	async function rescan() {
		rescanning = true;
		error = null;
		try {
			await rescanRecurring();
			await load();
		} catch (e) {
			error = extractErrorDetail(e);
		} finally {
			rescanning = false;
		}
	}
</script>

<div class="recurring-page">
	<div class="header">
		<h1>Recurring Payments</h1>
		<button class="rescan-button" onclick={rescan} disabled={rescanning}>
			{rescanning ? 'Rescanning...' : 'Rescan'}
		</button>
	</div>

	{#if error}
		<p class="error">{error}</p>
	{/if}

	{#if loading}
		<p class="muted">Loading...</p>
	{:else}
		<section class="section">
			<h2>Suggested</h2>
			{#if suggested.length === 0}
				<div class="empty-state">
					<p>No suggestions yet. Import more history to detect patterns, or rescan.</p>
					<button class="rescan-button" onclick={rescan} disabled={rescanning}>
						{rescanning ? 'Rescanning...' : 'Rescan'}
					</button>
				</div>
			{:else}
				<div class="row-list">
					{#each suggested as payment (payment.id)}
						<div class="row-card">
							<div class="row-main">
								<div class="row-info">
									<span class="row-name">
										{payment.name}
										{#if payment.is_income}
											<span class="badge income">income</span>
										{/if}
									</span>
									<span class="row-detail">
										{formatEuro(payment.expected_amount)} &middot; {cadenceLabel(payment)}
									</span>
									<span class="row-detail muted">
										Last seen {payment.last_seen ? formatDate(payment.last_seen) : 'unknown'} &middot; {payment.occurrence_count} occurrence{payment.occurrence_count === 1 ? '' : 's'}
									</span>
								</div>
								<div class="row-actions">
									<button class="confirm-button" onclick={() => startConfirm(payment)}>Confirm</button>
									<button class="dismiss-button" onclick={() => dismissSuggested(payment.id)}>Dismiss</button>
								</div>
							</div>

							{#if confirmingId === payment.id}
								<div class="inline-form">
									<label>
										Name
										<input type="text" bind:value={confirmName} />
									</label>
									<label>
										Category
										<CategoryInput value={confirmCategoryId} onchange={(id) => (confirmCategoryId = id)} />
									</label>
									<div class="inline-form-actions">
										<button class="save-button" onclick={() => saveConfirm(payment.id)}>Save</button>
										<button class="cancel-button" onclick={cancelConfirm}>Cancel</button>
									</div>
								</div>
							{/if}
						</div>
					{/each}
				</div>
			{/if}
		</section>

		<section class="section">
			<h2>Confirmed</h2>
			{#if confirmed.length === 0}
				<p class="muted">No confirmed recurring payments yet.</p>
			{:else}
				<div class="row-list">
					{#each confirmed as payment (payment.id)}
						{@const rowNotices = noticesFor(payment.id)}
						<div class="row-card">
							<div class="row-main">
								<div class="row-info">
									<span class="row-name">
										{payment.name}
										{#if payment.is_income}
											<span class="badge income">income</span>
										{/if}
									</span>
									<span class="row-detail">
										{formatEuro(payment.expected_amount)} &middot; {cadenceLabel(payment)}
									</span>
									<span class="row-detail muted">
										Last seen {payment.last_seen ? formatDate(payment.last_seen) : 'unknown'} &middot; {payment.occurrence_count} occurrence{payment.occurrence_count === 1 ? '' : 's'}
										{#if payment.next_expected}
											&middot; Next expected {formatDate(payment.next_expected)}
										{/if}
									</span>
									{#if payment.id === salaryPaymentId}
										<span class="row-detail hint">Looks like your salary</span>
									{/if}
									{#each rowNotices as notice}
										<span class="notice" class:amount-changed={notice.type === 'amount_changed'} class:possibly-missed={notice.type === 'possibly_missed'}>
											{notice.detail}
										</span>
									{/each}
								</div>
								<div class="row-actions">
									<button class="edit-button" onclick={() => startEdit(payment)}>Edit</button>
									<button class="dismiss-button" onclick={() => stopTracking(payment)}>Stop tracking</button>
								</div>
							</div>

							{#if editingId === payment.id}
								<div class="inline-form">
									<label>
										Name
										<input type="text" bind:value={editName} />
									</label>
									<label>
										Category
										<CategoryInput value={editCategoryId} onchange={(id) => (editCategoryId = id)} />
									</label>
									<label>
										Expected amount
										<input type="number" step="0.01" bind:value={editExpectedAmount} />
									</label>
									<div class="inline-form-actions">
										<button class="save-button" onclick={() => saveEdit(payment.id)}>Save</button>
										<button class="cancel-button" onclick={cancelEdit}>Cancel</button>
									</div>
								</div>
							{/if}
						</div>
					{/each}
				</div>
			{/if}
		</section>

		<section class="section">
			<button class="collapse-toggle" onclick={toggleDismissed}>
				<h2>Dismissed {dismissedExpanded ? '▾' : '▸'}</h2>
			</button>
			{#if dismissedExpanded}
				{#if dismissedLoading}
					<p class="muted">Loading...</p>
				{:else if dismissed.length === 0}
					<p class="muted">Nothing dismissed.</p>
				{:else}
					<div class="row-list">
						{#each dismissed as payment (payment.id)}
							<div class="row-card">
								<div class="row-main">
									<div class="row-info">
										<span class="row-name">
											{payment.name}
											{#if payment.is_income}
												<span class="badge income">income</span>
											{/if}
										</span>
										<span class="row-detail">
											{formatEuro(payment.expected_amount)} &middot; {cadenceLabel(payment)}
										</span>
										<span class="row-detail muted">
											Last seen {payment.last_seen ? formatDate(payment.last_seen) : 'unknown'} &middot; {payment.occurrence_count} occurrence{payment.occurrence_count === 1 ? '' : 's'}
										</span>
									</div>
									<div class="row-actions">
										<button class="confirm-button" onclick={() => reconfirm(payment.id)}>Re-confirm</button>
									</div>
								</div>
							</div>
						{/each}
					</div>
				{/if}
			{/if}
		</section>
	{/if}
</div>

<style>
	.recurring-page { max-width: 900px; }
	.header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		margin-bottom: 1.5rem;
	}
	h1 { margin: 0; color: #1a1a1a; }
	h2 { margin: 0 0 1rem; font-size: 1.1rem; }
	.collapse-toggle {
		background: none;
		border: none;
		padding: 0;
		cursor: pointer;
		text-align: left;
		width: 100%;
	}
	.collapse-toggle h2 { color: #444; }
	.muted { color: #999; font-style: italic; }
	.error {
		background: #fef2f2;
		color: #b91c1c;
		padding: 0.75rem 1rem;
		border-radius: 6px;
		margin-bottom: 1rem;
	}

	.section {
		background: white;
		padding: 1.5rem;
		border-radius: 8px;
		margin-bottom: 1.5rem;
	}

	.empty-state {
		text-align: center;
		padding: 2rem;
		color: #666;
	}
	.empty-state p { margin-bottom: 1rem; }

	.rescan-button {
		background: #2d6a4f;
		color: white;
		border: none;
		padding: 0.5rem 1rem;
		border-radius: 6px;
		cursor: pointer;
		font-size: 0.9rem;
	}
	.rescan-button:hover { background: #1b4332; }
	.rescan-button:disabled { opacity: 0.6; cursor: default; }

	.row-list { display: flex; flex-direction: column; gap: 0.75rem; }
	.row-card {
		border: 1px solid #eee;
		border-radius: 8px;
		padding: 1rem;
	}
	.row-main {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
		gap: 1rem;
		flex-wrap: wrap;
	}
	.row-info {
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
	}
	.row-name {
		font-weight: 600;
		font-size: 1rem;
		display: flex;
		align-items: center;
		gap: 0.5rem;
	}
	.row-detail {
		font-size: 0.85rem;
		color: #444;
	}
	.row-detail.hint {
		color: #16a34a;
		font-style: italic;
	}

	.badge {
		font-size: 0.7rem;
		font-weight: 600;
		padding: 0.1rem 0.5rem;
		border-radius: 999px;
	}
	.badge.income {
		background: #dcfce7;
		color: #15803d;
	}

	.notice {
		font-size: 0.8rem;
		font-weight: 500;
		padding: 0.2rem 0;
	}
	.notice.amount-changed { color: #a16207; }
	.notice.possibly-missed { color: #b91c1c; }

	.row-actions {
		display: flex;
		gap: 0.5rem;
		flex-shrink: 0;
	}

	.confirm-button, .edit-button, .save-button {
		background: #2d6a4f;
		color: white;
		border: none;
		padding: 0.4rem 0.8rem;
		border-radius: 6px;
		cursor: pointer;
		font-size: 0.85rem;
	}
	.confirm-button:hover, .edit-button:hover, .save-button:hover { background: #1b4332; }

	.dismiss-button, .cancel-button {
		background: none;
		border: 1px solid #ddd;
		color: #666;
		padding: 0.4rem 0.8rem;
		border-radius: 6px;
		cursor: pointer;
		font-size: 0.85rem;
	}
	.dismiss-button:hover, .cancel-button:hover { background: #f5f5f5; }

	.inline-form {
		margin-top: 1rem;
		padding-top: 1rem;
		border-top: 1px solid #eee;
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
	}
	.inline-form label {
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
		font-size: 0.8rem;
		color: #666;
	}
	.inline-form input {
		padding: 0.4rem 0.5rem;
		border: 1px solid #ddd;
		border-radius: 4px;
		font-size: 0.9rem;
	}
	.inline-form-actions {
		display: flex;
		gap: 0.5rem;
	}
</style>
