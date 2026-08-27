import type { Transaction, TransactionFlags } from '$lib/api';

/** Returns a new array with the given flags applied to the selected rows,
 * mirroring the backend's bulk-flags semantics: a label implies incidental,
 * clearing incidental clears the label. */
export function applyFlagsToTransactions(
	transactions: Transaction[],
	ids: number[],
	flags: TransactionFlags
): Transaction[] {
	const idSet = new Set(ids);
	return transactions.map((t) => {
		if (!idSet.has(t.id)) return t;
		const next = { ...t };
		if (flags.is_incidental === false) {
			next.is_incidental = false;
			next.incidental_label_id = null;
		} else {
			if (flags.is_incidental === true) next.is_incidental = true;
			if (flags.incidental_label_id != null) {
				next.is_incidental = true;
				next.incidental_label_id = flags.incidental_label_id;
			}
		}
		if (flags.is_internal_transfer !== undefined) {
			next.is_internal_transfer = flags.is_internal_transfer;
		}
		return next;
	});
}
