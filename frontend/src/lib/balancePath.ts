export interface ChartPoint {
	date: string;
	balance: number;
}

export function buildBalancePath(
	points: ChartPoint[],
	width: number,
	height: number
): { path: string; min: number; max: number } {
	if (points.length === 0) return { path: '', min: 0, max: 0 };

	const balances = points.map((p) => p.balance);
	const min = Math.min(...balances);
	const max = Math.max(...balances);
	const range = max - min;

	const times = points.map((p) => new Date(p.date).getTime());
	const tMin = Math.min(...times);
	const tSpan = Math.max(...times) - tMin;

	const segments = points.map((p, i) => {
		const x = tSpan === 0 ? 0 : ((times[i] - tMin) / tSpan) * width;
		const y = range === 0 ? height / 2 : height - ((p.balance - min) / range) * height;
		return `${i === 0 ? 'M' : 'L'} ${round2(x)} ${round2(y)}`;
	});
	return { path: segments.join(' '), min, max };
}

function round2(n: number): number {
	return Math.round(n * 100) / 100;
}
