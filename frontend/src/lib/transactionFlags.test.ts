import { describe, expect, it } from 'vitest';
import { applyFlagsToTransactions } from './transactionFlags';
import type { Transaction } from './api';

function tx(id: number, overrides: Partial<Transaction> = {}): Transaction {
	return {
		id,
		datum: '2026-08-01',
		rekening: 'NL00TEST0000000001',
		tegenrekening: null,
		naam: 'Test',
		bedrag: -10,
		valuta: 'EUR',
		omschrijving: 'test',
		categorie: 'Test',
		category_id: null,
		category_name: null,
		merchant_name: null,
		type: 'BEA',
		code: 'GT',
		has_receipt: false,
		created_at: '2026-08-01T00:00:00',
		is_internal_transfer: false,
		is_incidental: false,
		incidental_label_id: null,
		offset_total: 0,
		is_offset_income: false,
		...overrides
	};
}

describe('applyFlagsToTransactions', () => {
	it('only touches selected rows and keeps others by reference', () => {
		const rows = [tx(1), tx(2)];
		const result = applyFlagsToTransactions(rows, [1], { is_incidental: true });
		expect(result[0].is_incidental).toBe(true);
		expect(result[1]).toBe(rows[1]);
		expect(rows[0].is_incidental).toBe(false); // input not mutated
	});

	it('label implies incidental', () => {
		const result = applyFlagsToTransactions([tx(1)], [1], { incidental_label_id: 7 });
		expect(result[0].is_incidental).toBe(true);
		expect(result[0].incidental_label_id).toBe(7);
	});

	it('clearing incidental clears the label even when a label is supplied', () => {
		const rows = [tx(1, { is_incidental: true, incidental_label_id: 7 })];
		const result = applyFlagsToTransactions(rows, [1], {
			is_incidental: false,
			incidental_label_id: 7
		});
		expect(result[0].is_incidental).toBe(false);
		expect(result[0].incidental_label_id).toBeNull();
	});

	it('sets and clears the transfer flag', () => {
		const on = applyFlagsToTransactions([tx(1)], [1], { is_internal_transfer: true });
		expect(on[0].is_internal_transfer).toBe(true);
		const off = applyFlagsToTransactions(on, [1], { is_internal_transfer: false });
		expect(off[0].is_internal_transfer).toBe(false);
	});
});
