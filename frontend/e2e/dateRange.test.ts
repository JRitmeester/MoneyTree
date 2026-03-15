import { test, expect } from '@playwright/test';

test.describe('date range persistence', () => {
	test('selected period persists across page navigation', async ({ page }) => {
		await page.goto('/');

		// Select 2W preset on dashboard
		await page.getByRole('button', { name: '2W' }).click();
		await expect(page.getByRole('button', { name: '2W' })).toHaveClass(/active/);

		// Navigate to transactions
		await page.goto('/transactions');

		// 2W should still be active
		await expect(page.getByRole('button', { name: '2W' })).toHaveClass(/active/);
	});

	test('selected period survives page refresh', async ({ page }) => {
		await page.goto('/');

		// Select 3M preset
		await page.getByRole('button', { name: '3M' }).click();
		await expect(page.getByRole('button', { name: '3M' })).toHaveClass(/active/);

		// Refresh
		await page.reload();

		// 3M should still be active
		await expect(page.getByRole('button', { name: '3M' })).toHaveClass(/active/);
	});
});
