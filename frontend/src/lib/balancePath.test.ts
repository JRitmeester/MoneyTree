import { describe, expect, it } from 'vitest';
import { buildBalancePath } from './balancePath';

describe('buildBalancePath', () => {
	it('returns empty path for no points', () => {
		expect(buildBalancePath([], 100, 40)).toEqual({ path: '', min: 0, max: 0 });
	});

	it('maps first and last point to the horizontal extremes', () => {
		const points = [
			{ date: '2026-04-01', balance: 0 },
			{ date: '2026-04-15', balance: 50 },
			{ date: '2026-04-30', balance: 100 }
		];
		const { path, min, max } = buildBalancePath(points, 100, 40);
		expect(min).toBe(0);
		expect(max).toBe(100);
		// First point: x=0, y=40 (lowest balance at bottom). Last: x=100, y=0.
		expect(path.startsWith('M 0 40')).toBe(true);
		expect(path.endsWith('L 100 0')).toBe(true);
	});

	it('handles a flat series without dividing by zero', () => {
		const points = [
			{ date: '2026-04-01', balance: 500 },
			{ date: '2026-04-02', balance: 500 }
		];
		const { path } = buildBalancePath(points, 100, 40);
		expect(path).toContain('M 0 20');
	});
});
