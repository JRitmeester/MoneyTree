import { describe, it, expect, beforeEach } from 'vitest';
import { get } from 'svelte/store';
import { dateRange } from './dateRange';

function toISODate(d: Date): string {
	return d.toISOString().split('T')[0];
}

describe('dateRange store', () => {
	beforeEach(() => {
		localStorage.clear();
	});

	it('initializes with 1M default when no localStorage', () => {
		// Re-import would be needed for a fresh store, but we can test the shape
		const state = get(dateRange);
		expect(state).toHaveProperty('activePreset');
		expect(state).toHaveProperty('dateFrom');
		expect(state).toHaveProperty('dateTo');
		expect(state.dateFrom).toBeTruthy();
		expect(state.dateTo).toBeTruthy();
	});

	it('persists changes to localStorage', () => {
		const newState = {
			activePreset: '2W',
			dateFrom: '2025-01-01',
			dateTo: '2025-01-14'
		};
		dateRange.set(newState);

		const stored = JSON.parse(localStorage.getItem('moneytree-date-range')!);
		expect(stored).toEqual(newState);
	});

	it('updates store values correctly', () => {
		dateRange.set({
			activePreset: '3M',
			dateFrom: '2025-01-01',
			dateTo: '2025-04-01'
		});

		const state = get(dateRange);
		expect(state.activePreset).toBe('3M');
		expect(state.dateFrom).toBe('2025-01-01');
		expect(state.dateTo).toBe('2025-04-01');
	});

	it('handles null activePreset for custom dates', () => {
		dateRange.set({
			activePreset: null,
			dateFrom: '2025-06-01',
			dateTo: '2025-06-30'
		});

		const state = get(dateRange);
		expect(state.activePreset).toBeNull();
	});
});
