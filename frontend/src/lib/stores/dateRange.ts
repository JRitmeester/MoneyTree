import { writable } from 'svelte/store';

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
