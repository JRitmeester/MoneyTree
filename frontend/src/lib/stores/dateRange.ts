import { writable } from 'svelte/store';
import { getCashflowPeriods, type CashflowPeriod } from '$lib/api';

const STORAGE_KEY = 'moneytree-date-range';

export interface DateRangeState {
	activePreset: string | null;
	dateFrom: string;
	dateTo: string;
}

function toISODate(d: Date): string {
	return d.toISOString().split('T')[0];
}

function createDefault(): DateRangeState {
	const to = new Date();
	const from = new Date();
	from.setMonth(from.getMonth() - 1);
	return { activePreset: '1M', dateFrom: toISODate(from), dateTo: toISODate(to) };
}

function loadFromStorage(): DateRangeState {
	if (typeof localStorage === 'undefined') return createDefault();
	try {
		const stored = localStorage.getItem(STORAGE_KEY);
		if (stored) {
			const parsed = JSON.parse(stored);
			if (parsed.dateFrom && parsed.dateTo) return parsed;
		}
	} catch {
		// Ignore parse errors
	}
	return createDefault();
}

function createDateRangeStore() {
	const store = writable<DateRangeState>(loadFromStorage());

	store.subscribe((value) => {
		if (typeof localStorage !== 'undefined') {
			try {
				localStorage.setItem(STORAGE_KEY, JSON.stringify(value));
			} catch {
				// Ignore storage errors
			}
		}
	});

	return store;
}

export const dateRange = createDateRangeStore();

// Pay periods are fetched once per app session and memoized: several pages
// share DateRangeFilter, and the periods rarely change within a session.
// Invalidated by invalidatePayPeriods(), called wherever the salary pattern's
// confirmed status or occurrences could change (recurring confirm/re-confirm/
// stop-tracking on /recurring).
let payPeriodsPromise: Promise<CashflowPeriod[]> | null = null;

export function getPayPeriods(): Promise<CashflowPeriod[]> {
	if (!payPeriodsPromise) {
		payPeriodsPromise = getCashflowPeriods().catch((err) => {
			// Allow a retry on the next call instead of caching a failure.
			payPeriodsPromise = null;
			throw err;
		});
	}
	return payPeriodsPromise;
}

export function invalidatePayPeriods(): void {
	payPeriodsPromise = null;
}
