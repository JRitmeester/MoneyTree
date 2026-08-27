/** Extracts a user-friendly message from an error thrown by the api.ts
 * `request` helper. Backend errors surface as `Error(`${status}: ${body}`)`;
 * when the body is JSON with a `detail` field (FastAPI's convention), that
 * detail is returned instead of the raw status/body string. */
export function extractErrorDetail(e: unknown): string {
	const message = (e as { message?: string })?.message ?? String(e);
	const jsonStart = message.indexOf('{');
	if (jsonStart === -1) return message;
	try {
		const parsed = JSON.parse(message.slice(jsonStart));
		return parsed.detail ?? message;
	} catch {
		return message;
	}
}
