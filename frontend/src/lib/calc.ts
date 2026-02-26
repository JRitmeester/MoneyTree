/**
 * Evaluate a simple arithmetic expression string.
 * Supports +, -, *, x (as multiply), parentheses, and decimal numbers.
 * Returns the result rounded to 2 decimal places, or NaN if invalid.
 */
export function evaluateExpression(expr: string): number {
	if (!expr || !expr.trim()) return 0;

	// Normalize: replace 'x' with '*', remove spaces
	let normalized = expr.replace(/x/gi, '*').replace(/\s+/g, '');

	// Only allow digits, decimal points, +, -, *, (, )
	if (!/^[0-9+\-*().]+$/.test(normalized)) return NaN;

	// Reject empty parens, double operators, etc.
	if (/[+\-*]{2,}/.test(normalized.replace(/[+\-]\s*\(/g, ''))) return NaN;

	try {
		// Use Function constructor for safe-ish eval of pure arithmetic
		const result = new Function(`"use strict"; return (${normalized})`)() as number;
		if (typeof result !== 'number' || !isFinite(result)) return NaN;
		return Math.round(result * 100) / 100;
	} catch {
		return NaN;
	}
}

/**
 * Evaluate the expression and return the formatted string.
 * If the input is already a plain number, returns it as-is (with 2 decimals).
 * If it's an expression, evaluates and returns the result.
 * Returns the original string if evaluation fails.
 */
export function resolveAmount(input: string): string {
	const trimmed = input.trim();
	if (!trimmed) return '';

	// If it's already a simple number, just format it
	const simple = parseFloat(trimmed);
	if (String(simple) === trimmed || /^-?\d+\.?\d*$/.test(trimmed)) {
		return simple.toFixed(2);
	}

	// Try evaluating as expression
	const result = evaluateExpression(trimmed);
	if (isNaN(result)) return trimmed; // leave as-is if invalid
	return result.toFixed(2);
}
