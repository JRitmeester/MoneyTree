import { describe, expect, it } from 'vitest';
import { amortizedYearlyCosts } from './insights';
import type { RecurringPayment } from './api';

function payment(overrides: Partial<RecurringPayment>): RecurringPayment {
	return {
		id: 1,
		merchant_pattern: 'pattern',
		counterparty_iban: null,
		name: 'Test',
		expected_amount: -120,
		amount_tolerance: 0.15,
		cadence: 'yearly',
		expected_day: null,
		anchor_date: '2025-01-01',
		status: 'confirmed',
		category_id: null,
		is_income: false,
		created_at: '2025-01-01T00:00:00Z',
		updated_at: '2025-01-01T00:00:00Z',
		next_expected: null,
		occurrence_count: 1,
		last_seen: null,
		...overrides
	};
}

describe('amortizedYearlyCosts', () => {
	it('includes confirmed yearly payments with their monthly equivalent', () => {
		const result = amortizedYearlyCosts([payment({ id: 1, name: 'Road tax', expected_amount: -240 })]);
		expect(result).toEqual([
			{ id: 1, name: 'Road tax', amount: 240, monthly_equivalent: 20 }
		]);
	});

	it('excludes suggested payments even if yearly', () => {
		const result = amortizedYearlyCosts([payment({ status: 'suggested' })]);
		expect(result).toEqual([]);
	});

	it('excludes dismissed payments', () => {
		const result = amortizedYearlyCosts([payment({ status: 'dismissed' })]);
		expect(result).toEqual([]);
	});

	it('excludes non-yearly cadences', () => {
		const result = amortizedYearlyCosts([payment({ cadence: 'monthly' })]);
		expect(result).toEqual([]);
	});

	it('sorts by amount descending', () => {
		const result = amortizedYearlyCosts([
			payment({ id: 1, name: 'Small', expected_amount: -60 }),
			payment({ id: 2, name: 'Big', expected_amount: -600 })
		]);
		expect(result.map((r) => r.name)).toEqual(['Big', 'Small']);
	});
});
