import type { RecurringPayment } from './api';

export interface AmortizedYearlyCost {
	id: number;
	name: string;
	amount: number;
	monthly_equivalent: number;
}

/** Confirmed yearly recurring payments, expressed as a yearly amount plus its
 * monthly equivalent ("X per month equivalent"). Suggested/dismissed
 * payments and non-yearly cadences are excluded: this block is only about
 * costs that are locked in and paid once a year. */
export function amortizedYearlyCosts(payments: RecurringPayment[]): AmortizedYearlyCost[] {
	return payments
		.filter((p) => p.status === 'confirmed' && p.cadence === 'yearly')
		.map((p) => {
			const amount = Math.abs(p.expected_amount);
			return { id: p.id, name: p.name, amount, monthly_equivalent: amount / 12 };
		})
		.sort((a, b) => b.amount - a.amount);
}
