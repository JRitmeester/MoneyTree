import { describe, expect, it } from 'vitest';

import { extractErrorDetail } from './errors';

describe('extractErrorDetail', () => {
	it('returns string details as-is', () => {
		const e = new Error('409: {"detail": "A bucket with this name already exists"}');
		expect(extractErrorDetail(e)).toBe('A bucket with this name already exists');
	});

	it('flattens pydantic validation arrays to their messages', () => {
		const e = new Error(
			'422: {"detail": [{"type": "value_error", "loc": ["body", "value"], "msg": "Percentage must be between 0 and 100"}]}'
		);
		expect(extractErrorDetail(e)).toBe('Percentage must be between 0 and 100');
	});

	it('never renders [object Object] for object details', () => {
		const e = new Error('422: {"detail": [{"unexpected": "shape"}]}');
		expect(extractErrorDetail(e)).not.toContain('[object Object]');
	});

	it('falls back to the raw message for non-JSON bodies', () => {
		const e = new Error('502: Bad Gateway');
		expect(extractErrorDetail(e)).toBe('502: Bad Gateway');
	});
});
