import { describe, expect, it } from 'vitest';
import { computeUndoGroups } from './undo';

describe('computeUndoGroups', () => {
	it('groups ids with identical values together', () => {
		const previous = new Map<number, string>([
			[1, 'a'],
			[2, 'b'],
			[3, 'a'],
		]);
		const groups = computeUndoGroups(previous);
		expect(groups).toEqual([
			{ value: 'a', ids: [1, 3] },
			{ value: 'b', ids: [2] },
		]);
	});

	it('produces one group per id when all values differ', () => {
		const previous = new Map<number, number | null>([
			[1, null],
			[2, 5],
			[3, 7],
		]);
		const groups = computeUndoGroups(previous);
		expect(groups).toEqual([
			{ value: null, ids: [1] },
			{ value: 5, ids: [2] },
			{ value: 7, ids: [3] },
		]);
	});

	it('produces a single group when all ids share the same value', () => {
		const previous = new Map<number, number | null>([
			[10, null],
			[11, null],
			[12, null],
		]);
		const groups = computeUndoGroups(previous);
		expect(groups).toEqual([{ value: null, ids: [10, 11, 12] }]);
	});

	it('groups by deep equality for object values', () => {
		interface Flags {
			is_incidental: boolean;
			incidental_label_id: number | null;
		}
		const valueA: Flags = { is_incidental: true, incidental_label_id: 7 };
		const valueB: Flags = { is_incidental: true, incidental_label_id: 7 };
		const valueC: Flags = { is_incidental: false, incidental_label_id: null };
		const previous = new Map<number, Flags>([
			[1, valueA],
			[2, valueB],
			[3, valueC],
		]);
		const groups = computeUndoGroups(previous);
		expect(groups).toEqual([
			{ value: valueA, ids: [1, 2] },
			{ value: valueC, ids: [3] },
		]);
	});

	it('returns a stable, insertion-ordered output', () => {
		const previous = new Map<number, string>([
			[5, 'z'],
			[1, 'a'],
			[3, 'z'],
			[2, 'a'],
		]);
		const groups = computeUndoGroups(previous);
		expect(groups).toEqual([
			{ value: 'z', ids: [5, 3] },
			{ value: 'a', ids: [1, 2] },
		]);
	});

	it('returns an empty array for an empty map', () => {
		expect(computeUndoGroups(new Map())).toEqual([]);
	});
});
