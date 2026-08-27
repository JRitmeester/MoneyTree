/** One group of ids that previously shared the same value, produced by
 * computeUndoGroups. Consumers issue one restore call per group: a bulk
 * call when a group has multiple ids, a per-id call as a fallback when a
 * group is a single id (or when the transport has no bulk form for the
 * value, e.g. clearing to null). */
export interface UndoGroup<T> {
	value: T;
	ids: number[];
}

/** Groups ids by identical previous value so a bulk action can be undone
 * with as few restore calls as possible. Values are compared by deep
 * (structural) equality via JSON serialization, which is sufficient for
 * the plain data values (numbers, null, small flag objects) this is used
 * for. Output order is stable: groups appear in the order their value was
 * first seen, and ids within a group keep their insertion order. */
export function computeUndoGroups<T>(previous: Map<number, T>): UndoGroup<T>[] {
	const groups: UndoGroup<T>[] = [];
	const keyToIndex = new Map<string, number>();

	for (const [id, value] of previous) {
		const key = JSON.stringify(value);
		let index = keyToIndex.get(key);
		if (index === undefined) {
			index = groups.length;
			keyToIndex.set(key, index);
			groups.push({ value, ids: [] });
		}
		groups[index].ids.push(id);
	}

	return groups;
}
