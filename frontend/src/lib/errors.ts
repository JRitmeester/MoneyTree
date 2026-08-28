/** Extracts a user-friendly message from an error thrown by the api.ts
 * `request` helper. Backend errors surface as `Error(`${status}: ${body}`)`;
 * when the body is JSON with a `detail` field (FastAPI's convention), that
 * detail is returned instead of the raw status/body string. Pydantic
 * validation errors carry `detail` as an array of objects; those are
 * flattened to their human-readable `msg` fields. */
export function extractErrorDetail(e: unknown): string {
	const message = (e as { message?: string })?.message ?? String(e);
	const jsonStart = message.indexOf('{');
	if (jsonStart === -1) return message;
	try {
		const parsed = JSON.parse(message.slice(jsonStart));
		const detail = parsed.detail;
		if (typeof detail === 'string') return detail;
		if (Array.isArray(detail)) {
			const msgs = detail
				.map((item) => {
					if (typeof item === 'object' && item !== null) {
						return 'msg' in item ? String(item.msg) : JSON.stringify(item);
					}
					return String(item);
				})
				.filter(Boolean);
			if (msgs.length > 0) return msgs.join('; ');
		}
		if (detail !== undefined && detail !== null) return JSON.stringify(detail);
		return message;
	} catch {
		return message;
	}
}
