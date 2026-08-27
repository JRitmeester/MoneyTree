import { describe, it, expect, vi, beforeEach, afterEach, type Mock } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/svelte';
import UncategorizedPage from './+page.svelte';

// Mock the dateRange store to avoid auto-filtering in tests
vi.mock('$lib/stores/dateRange', () => {
	const { writable } = require('svelte/store');
	return {
		dateRange: writable({ activePreset: null, dateFrom: '', dateTo: '' }),
	};
});

// Mock the api module
vi.mock('$lib/api', () => ({
	getUncategorized: vi.fn(),
	categorizeSelected: vi.fn(),
	bulkCategorize: vi.fn(),
	getCategories: vi.fn(),
	createCategory: vi.fn(),
	formatEuro: (amount: number) =>
		new Intl.NumberFormat('nl-NL', { style: 'currency', currency: 'EUR' }).format(amount),
	formatDate: (dateStr: string) =>
		new Date(dateStr).toLocaleDateString('nl-NL', {
			day: '2-digit',
			month: '2-digit',
			year: 'numeric',
		}),
}));

import { getUncategorized, categorizeSelected, bulkCategorize, getCategories } from '$lib/api';
import { dateRange } from '$lib/stores/dateRange';

const mockGroups = [
	{
		bank_category: 'Boodschappen',
		count: 2,
		total: 35.5,
		has_mapping: false,
		transactions: [
			{
				id: 1,
				datum: '2025-01-15',
				bedrag: -20.0,
				merchant_name: 'Albert Heijn',
				naam: null,
				omschrijving: 'Boodschappen AH',
			},
			{
				id: 2,
				datum: '2025-01-14',
				bedrag: -15.5,
				merchant_name: null,
				naam: 'Jumbo',
				omschrijving: 'Boodschappen Jumbo',
			},
		],
	},
	{
		bank_category: 'Horeca',
		count: 1,
		total: 25.0,
		has_mapping: false,
		transactions: [
			{
				id: 3,
				datum: '2025-01-13',
				bedrag: -25.0,
				merchant_name: 'Restaurant',
				naam: null,
				omschrijving: 'Dinner',
			},
		],
	},
];

describe('Uncategorized Page', () => {
	afterEach(() => {
		cleanup();
	});

	beforeEach(() => {
		vi.clearAllMocks();
		(getCategories as Mock).mockResolvedValue([
			{ id: 10, name: 'Eten', parent_id: null, is_fixed: false, category_type: 'expense', children: [] },
		]);
	});

	it('shows loading state initially', () => {
		(getUncategorized as Mock).mockReturnValue(new Promise(() => {})); // never resolves
		render(UncategorizedPage);
		expect(screen.getByText('Loading...')).toBeInTheDocument();
	});

	it('shows empty state when no uncategorized transactions', async () => {
		(getUncategorized as Mock).mockResolvedValue([]);
		render(UncategorizedPage);
		expect(await screen.findByText('All transactions are categorized.')).toBeInTheDocument();
	});

	it('renders groups with transaction counts', async () => {
		(getUncategorized as Mock).mockResolvedValue(mockGroups);
		render(UncategorizedPage);

		expect(await screen.findByText('Boodschappen')).toBeInTheDocument();
		expect(screen.getByText('Horeca')).toBeInTheDocument();
		expect(screen.getByText('Albert Heijn')).toBeInTheDocument();
		expect(screen.getByText('Jumbo')).toBeInTheDocument();
		expect(screen.getByText('Restaurant')).toBeInTheDocument();
	});

	it('shows sticky bar with 0 selected initially', async () => {
		(getUncategorized as Mock).mockResolvedValue(mockGroups);
		render(UncategorizedPage);

		expect(await screen.findByText('0 selected')).toBeInTheDocument();
	});

	it('shows total transaction count in subtitle', async () => {
		(getUncategorized as Mock).mockResolvedValue(mockGroups);
		render(UncategorizedPage);

		expect(await screen.findByText(/3 transactions across 2 bank categories/)).toBeInTheDocument();
	});

	it('renders checkboxes for each transaction', async () => {
		(getUncategorized as Mock).mockResolvedValue(mockGroups);
		render(UncategorizedPage);

		await screen.findByText('Albert Heijn');
		// 3 transaction checkboxes + 2 group checkboxes = 5 total
		const checkboxes = screen.getAllByRole('checkbox');
		expect(checkboxes).toHaveLength(5);
	});

	it('toggles individual transaction selection', async () => {
		(getUncategorized as Mock).mockResolvedValue(mockGroups);
		render(UncategorizedPage);

		await screen.findByText('Albert Heijn');
		const checkboxes = screen.getAllByRole('checkbox');
		// First group checkbox, then tx checkboxes for group 1, then group 2 checkbox, then tx checkbox for group 2
		// Group 1 checkbox = index 0, tx1 = index 1, tx2 = index 2
		const tx1Checkbox = checkboxes[1];

		await fireEvent.click(tx1Checkbox);
		expect(screen.getByText('1 selected')).toBeInTheDocument();

		await fireEvent.click(tx1Checkbox);
		expect(screen.getByText('0 selected')).toBeInTheDocument();
	});

	it('selects all in group when group checkbox clicked', async () => {
		(getUncategorized as Mock).mockResolvedValue(mockGroups);
		render(UncategorizedPage);

		await screen.findByText('Albert Heijn');
		const checkboxes = screen.getAllByRole('checkbox');
		const groupCheckbox = checkboxes[0]; // first group checkbox

		await fireEvent.click(groupCheckbox);
		expect(screen.getByText('2 selected')).toBeInTheDocument();
	});

	it('deselects all in group when all are selected and group checkbox clicked', async () => {
		(getUncategorized as Mock).mockResolvedValue(mockGroups);
		render(UncategorizedPage);

		await screen.findByText('Albert Heijn');
		const checkboxes = screen.getAllByRole('checkbox');

		// Select both transactions individually
		await fireEvent.click(checkboxes[1]);
		await fireEvent.click(checkboxes[2]);
		expect(screen.getByText('2 selected')).toBeInTheDocument();

		// Click group checkbox to deselect all
		await fireEvent.click(checkboxes[0]);
		expect(screen.getByText('0 selected')).toBeInTheDocument();
	});

	it('apply button is disabled when no selection', async () => {
		(getUncategorized as Mock).mockResolvedValue(mockGroups);
		render(UncategorizedPage);

		const applyBtn = await screen.findByRole('button', { name: 'Apply' });
		expect(applyBtn).toBeDisabled();
	});

	it('selects across multiple groups', async () => {
		(getUncategorized as Mock).mockResolvedValue(mockGroups);
		render(UncategorizedPage);

		await screen.findByText('Albert Heijn');
		const checkboxes = screen.getAllByRole('checkbox');
		// tx1 from group1 (index 1) and tx3 from group2 (index 4)
		await fireEvent.click(checkboxes[1]);
		await fireEvent.click(checkboxes[4]);
		expect(screen.getByText('2 selected')).toBeInTheDocument();
	});

	it('removes categorized transactions after apply', async () => {
		(getUncategorized as Mock).mockResolvedValue(mockGroups);
		(categorizeSelected as Mock).mockResolvedValue({ updated: 2 });
		render(UncategorizedPage);

		await screen.findByText('Albert Heijn');
		const checkboxes = screen.getAllByRole('checkbox');

		// Select the first group
		await fireEvent.click(checkboxes[0]);
		expect(screen.getByText('2 selected')).toBeInTheDocument();

		// We can't easily test Apply without CategoryInput setting a value,
		// but we can verify the button state
		const applyBtn = screen.getByRole('button', { name: 'Apply' });
		// Still disabled because no category selected
		expect(applyBtn).toBeDisabled();
	});
});

describe('Search filter', () => {
	afterEach(() => {
		cleanup();
	});

	beforeEach(() => {
		vi.clearAllMocks();
		(getCategories as Mock).mockResolvedValue([
			{ id: 10, name: 'Eten', parent_id: null, is_fixed: false, category_type: 'expense', children: [] },
		]);
	});

	it('filters transactions by search query', async () => {
		(getUncategorized as Mock).mockResolvedValue(mockGroups);
		render(UncategorizedPage);

		await screen.findByText('Albert Heijn');
		const searchInput = screen.getByPlaceholderText('Filter descriptions...');

		await fireEvent.input(searchInput, { target: { value: 'albert' } });

		expect(screen.getByText('Albert Heijn')).toBeInTheDocument();
		expect(screen.queryByText('Jumbo')).not.toBeInTheDocument();
		expect(screen.queryByText('Restaurant')).not.toBeInTheDocument();
	});

	it('shows all transactions when search is empty', async () => {
		(getUncategorized as Mock).mockResolvedValue(mockGroups);
		render(UncategorizedPage);

		await screen.findByText('Albert Heijn');
		const searchInput = screen.getByPlaceholderText('Filter descriptions...');

		await fireEvent.input(searchInput, { target: { value: 'albert' } });
		expect(screen.queryByText('Jumbo')).not.toBeInTheDocument();

		await fireEvent.input(searchInput, { target: { value: '' } });
		expect(screen.getByText('Albert Heijn')).toBeInTheDocument();
		expect(screen.getByText('Jumbo')).toBeInTheDocument();
		expect(screen.getByText('Restaurant')).toBeInTheDocument();
	});

	it('matches across multiple groups', async () => {
		const groupsWithSharedTerm = [
			{
				bank_category: 'Boodschappen',
				count: 1,
				total: 20.0,
				has_mapping: false,
				transactions: [
					{ id: 1, datum: '2025-01-15', bedrag: -20.0, merchant_name: 'AH City', naam: null, omschrijving: 'Boodschappen AH' },
				],
			},
			{
				bank_category: 'Horeca',
				count: 1,
				total: 25.0,
				has_mapping: false,
				transactions: [
					{ id: 2, datum: '2025-01-13', bedrag: -25.0, merchant_name: null, naam: null, omschrijving: 'AH to go lunch' },
				],
			},
		];
		(getUncategorized as Mock).mockResolvedValue(groupsWithSharedTerm);
		render(UncategorizedPage);

		await screen.findByText('AH City');
		const searchInput = screen.getByPlaceholderText('Filter descriptions...');

		await fireEvent.input(searchInput, { target: { value: 'AH' } });

		expect(screen.getByText('Boodschappen')).toBeInTheDocument();
		expect(screen.getByText('Horeca')).toBeInTheDocument();
	});

	it('updates subtitle count to reflect filtered results', async () => {
		(getUncategorized as Mock).mockResolvedValue(mockGroups);
		render(UncategorizedPage);

		await screen.findByText(/3 transactions across 2 bank categories/);
		const searchInput = screen.getByPlaceholderText('Filter descriptions...');

		await fireEvent.input(searchInput, { target: { value: 'albert' } });

		expect(screen.getByText(/1 transaction across 1 bank categories/)).toBeInTheDocument();
	});

	it('clears filter when clear button is clicked', async () => {
		(getUncategorized as Mock).mockResolvedValue(mockGroups);
		render(UncategorizedPage);

		await screen.findByText('Albert Heijn');
		const searchInput = screen.getByPlaceholderText('Filter descriptions...');

		await fireEvent.input(searchInput, { target: { value: 'albert' } });
		expect(screen.queryByText('Jumbo')).not.toBeInTheDocument();

		const clearBtn = screen.getByText('×');
		await fireEvent.click(clearBtn);

		expect(screen.getByText('Albert Heijn')).toBeInTheDocument();
		expect(screen.getByText('Jumbo')).toBeInTheDocument();
		expect(screen.getByText('Restaurant')).toBeInTheDocument();
	});

	it('searches by naam field', async () => {
		(getUncategorized as Mock).mockResolvedValue(mockGroups);
		render(UncategorizedPage);

		await screen.findByText('Albert Heijn');
		const searchInput = screen.getByPlaceholderText('Filter descriptions...');

		// 'Jumbo' is in the naam field of tx2
		await fireEvent.input(searchInput, { target: { value: 'jumbo' } });

		expect(screen.queryByText('Albert Heijn')).not.toBeInTheDocument();
		expect(screen.getByText('Jumbo')).toBeInTheDocument();
	});

	it('hides groups with no matching transactions', async () => {
		(getUncategorized as Mock).mockResolvedValue(mockGroups);
		render(UncategorizedPage);

		await screen.findByText('Albert Heijn');
		const searchInput = screen.getByPlaceholderText('Filter descriptions...');

		// Only matches in Horeca group
		await fireEvent.input(searchInput, { target: { value: 'dinner' } });

		expect(screen.queryByText('Boodschappen')).not.toBeInTheDocument();
		expect(screen.getByText('Horeca')).toBeInTheDocument();
	});
});

describe('Date range filter', () => {
	const mockGroupsWithDates = [
		{
			bank_category: 'Boodschappen',
			count: 2,
			total: 35.5,
			has_mapping: false,
			transactions: [
				{ id: 1, datum: '2025-03-10', bedrag: -20.0, merchant_name: 'Albert Heijn', naam: null, omschrijving: 'AH' },
				{ id: 2, datum: '2025-01-05', bedrag: -15.5, merchant_name: 'Jumbo', naam: null, omschrijving: 'Jumbo' },
			],
		},
		{
			bank_category: 'Horeca',
			count: 1,
			total: 25.0,
			has_mapping: false,
			transactions: [
				{ id: 3, datum: '2025-02-15', bedrag: -25.0, merchant_name: 'Restaurant', naam: null, omschrijving: 'Dinner' },
			],
		},
	];

	afterEach(() => {
		cleanup();
	});

	beforeEach(() => {
		vi.clearAllMocks();
		(getCategories as Mock).mockResolvedValue([
			{ id: 10, name: 'Eten', parent_id: null, is_fixed: false, category_type: 'expense', children: [] },
		]);
	});

	it('renders date range filter component', async () => {
		(getUncategorized as Mock).mockResolvedValue(mockGroupsWithDates);
		render(UncategorizedPage);

		await screen.findByText('Albert Heijn');
		// DateRangeFilter renders preset buttons
		expect(screen.getByText('1M')).toBeInTheDocument();
		expect(screen.getByText('3M')).toBeInTheDocument();
	});

	it('filters transactions by date range', async () => {
		(getUncategorized as Mock).mockResolvedValue(mockGroupsWithDates);
		render(UncategorizedPage);

		await screen.findByText('Albert Heijn');
		const dateInputs = document.querySelectorAll<HTMLInputElement>('input[type="date"]');
		const fromInput = dateInputs[0];
		const toInput = dateInputs[1];

		// Simulate native input behavior: set value then fire both input and change
		fromInput.value = '2025-02-01';
		await fireEvent.input(fromInput);
		await fireEvent.change(fromInput);
		toInput.value = '2025-03-31';
		await fireEvent.input(toInput);
		await fireEvent.change(toInput);

		await waitFor(() => {
			expect(screen.queryByText('Jumbo')).not.toBeInTheDocument();
		});
		expect(screen.getByText('Albert Heijn')).toBeInTheDocument();
		expect(screen.getByText('Restaurant')).toBeInTheDocument();
	});

	it('hides groups entirely when no transactions match date range', async () => {
		(getUncategorized as Mock).mockResolvedValue(mockGroupsWithDates);
		render(UncategorizedPage);

		await screen.findByText('Albert Heijn');
		const dateInputs = document.querySelectorAll<HTMLInputElement>('input[type="date"]');
		const fromInput = dateInputs[0];
		const toInput = dateInputs[1];

		// Only March — Horeca group has no March transactions
		fromInput.value = '2025-03-01';
		await fireEvent.input(fromInput);
		await fireEvent.change(fromInput);
		toInput.value = '2025-03-31';
		await fireEvent.input(toInput);
		await fireEvent.change(toInput);

		await waitFor(() => {
			expect(screen.queryByText('Horeca')).not.toBeInTheDocument();
		});
		expect(screen.getByText('Albert Heijn')).toBeInTheDocument();
	});
});

describe('Bank category mapping', () => {
	afterEach(() => {
		cleanup();
	});

	beforeEach(() => {
		vi.clearAllMocks();
		// Earlier "Date range filter" tests persist real dates into this shared mocked
		// store; reset it so DateRangeFilter's mount effect doesn't inherit a stale
		// range that would filter out these tests' January 2025 fixtures.
		dateRange.set({ activePreset: null, dateFrom: '', dateTo: '' });
		(getCategories as Mock).mockResolvedValue([
			{ id: 10, name: 'Eten', parent_id: null, is_fixed: false, category_type: 'expense', children: [] },
		]);
	});

	async function selectCategory(assignInput: HTMLElement, name: string) {
		await fireEvent.input(assignInput, { target: { value: name } });
		await fireEvent.keyDown(assignInput, { key: 'Enter' });
	}

	it('shows a mapped badge for a group with an existing mapping', async () => {
		const mapped = [{ ...mockGroups[0], has_mapping: true }, mockGroups[1]];
		(getUncategorized as Mock).mockResolvedValue(mapped);
		render(UncategorizedPage);

		await screen.findByText('Boodschappen');
		expect(screen.getByTitle('Future imports map this bank category automatically')).toBeInTheDocument();
	});

	it('does not show a mapped badge for a group without a mapping', async () => {
		(getUncategorized as Mock).mockResolvedValue(mockGroups);
		render(UncategorizedPage);

		await screen.findByText('Boodschappen');
		expect(screen.queryByTitle('Future imports map this bank category automatically')).not.toBeInTheDocument();
	});

	it('shows the mapping checkbox when a whole group is selected', async () => {
		(getUncategorized as Mock).mockResolvedValue(mockGroups);
		render(UncategorizedPage);

		await screen.findByText('Albert Heijn');
		const checkboxes = screen.getAllByRole('checkbox');
		await fireEvent.click(checkboxes[0]); // group 1 checkbox, selects both its transactions

		expect(
			await screen.findByLabelText('Also map "Boodschappen" to this category for future imports')
		).toBeChecked();
	});

	it('does not show the mapping checkbox for a partial group selection', async () => {
		(getUncategorized as Mock).mockResolvedValue(mockGroups);
		render(UncategorizedPage);

		await screen.findByText('Albert Heijn');
		const checkboxes = screen.getAllByRole('checkbox');
		await fireEvent.click(checkboxes[1]); // only one transaction of group 1

		expect(
			screen.queryByLabelText(/Also map .* to this category for future imports/)
		).not.toBeInTheDocument();
	});

	it('does not show the mapping checkbox when selection spans multiple groups', async () => {
		(getUncategorized as Mock).mockResolvedValue(mockGroups);
		render(UncategorizedPage);

		await screen.findByText('Albert Heijn');
		const checkboxes = screen.getAllByRole('checkbox');
		await fireEvent.click(checkboxes[0]); // full group 1
		await fireEvent.click(checkboxes[3]); // group 2 checkbox

		expect(
			screen.queryByLabelText(/Also map .* to this category for future imports/)
		).not.toBeInTheDocument();
	});

	it('calls bulkCategorize with save_mapping when applying a full group selection', async () => {
		(getUncategorized as Mock).mockResolvedValue(mockGroups);
		(bulkCategorize as Mock).mockResolvedValue({ updated: 2 });
		render(UncategorizedPage);

		await screen.findByText('Albert Heijn');
		const checkboxes = screen.getAllByRole('checkbox');
		await fireEvent.click(checkboxes[0]); // full group 1

		const assignInput = screen.getByPlaceholderText('Assign category...');
		await selectCategory(assignInput, 'Eten');

		const mappingCheckbox = await screen.findByLabelText(
			'Also map "Boodschappen" to this category for future imports'
		);
		expect(mappingCheckbox).toBeChecked();

		const applyBtn = screen.getByRole('button', { name: 'Apply' });
		await fireEvent.click(applyBtn);

		await waitFor(() => {
			expect(bulkCategorize).toHaveBeenCalledWith({
				bank_category: 'Boodschappen',
				category_id: 10,
				save_mapping: true,
			});
		});
		expect(categorizeSelected).not.toHaveBeenCalled();
	});

	it('calls bulkCategorize with save_mapping false when the checkbox is unchecked', async () => {
		(getUncategorized as Mock).mockResolvedValue(mockGroups);
		(bulkCategorize as Mock).mockResolvedValue({ updated: 2 });
		render(UncategorizedPage);

		await screen.findByText('Albert Heijn');
		const checkboxes = screen.getAllByRole('checkbox');
		await fireEvent.click(checkboxes[0]); // full group 1

		const assignInput = screen.getByPlaceholderText('Assign category...');
		await selectCategory(assignInput, 'Eten');

		const mappingCheckbox = await screen.findByLabelText(
			'Also map "Boodschappen" to this category for future imports'
		);
		await fireEvent.click(mappingCheckbox);

		const applyBtn = screen.getByRole('button', { name: 'Apply' });
		await fireEvent.click(applyBtn);

		await waitFor(() => {
			expect(bulkCategorize).toHaveBeenCalledWith({
				bank_category: 'Boodschappen',
				category_id: 10,
				save_mapping: false,
			});
		});
	});

	it('calls categorizeSelected (not bulkCategorize) for a partial selection', async () => {
		(getUncategorized as Mock).mockResolvedValue(mockGroups);
		(categorizeSelected as Mock).mockResolvedValue({ updated: 1 });
		render(UncategorizedPage);

		await screen.findByText('Albert Heijn');
		const checkboxes = screen.getAllByRole('checkbox');
		await fireEvent.click(checkboxes[1]); // single transaction, group 1 not fully selected

		const assignInput = screen.getByPlaceholderText('Assign category...');
		await selectCategory(assignInput, 'Eten');

		const applyBtn = screen.getByRole('button', { name: 'Apply' });
		await fireEvent.click(applyBtn);

		await waitFor(() => {
			expect(categorizeSelected).toHaveBeenCalledWith({
				transaction_ids: [1],
				category_id: 10,
			});
		});
		expect(bulkCategorize).not.toHaveBeenCalled();
	});

	it('shows a link back to the dashboard in the empty state', async () => {
		(getUncategorized as Mock).mockResolvedValue([]);
		render(UncategorizedPage);

		await screen.findByText('All transactions are categorized.');
		const link = screen.getByRole('link', { name: /back to dashboard/i });
		expect(link).toHaveAttribute('href', '/');
	});

	it('uses categorize-selected (not bulk-categorize) when a filter hides part of the group', async () => {
		// Boodschappen has 2 transactions; filter to "AH" so only Albert Heijn is visible,
		// hiding the Jumbo transaction. Selecting all VISIBLE rows of the group must not be
		// treated as a whole-group selection, since bulk-categorize would recategorize the
		// hidden Jumbo transaction (and every other transaction sharing this bank category)
		// that the user never saw or selected.
		(getUncategorized as Mock).mockResolvedValue(mockGroups);
		(categorizeSelected as Mock).mockResolvedValue({ updated: 1 });
		render(UncategorizedPage);

		await screen.findByText('Albert Heijn');
		const descriptionInput = screen.getByPlaceholderText('Filter by description...');
		await fireEvent.input(descriptionInput, { target: { value: 'AH' } });

		expect(screen.queryByText('Jumbo')).not.toBeInTheDocument();

		// Select all visible rows of the (now partially hidden) Boodschappen group.
		const checkboxes = screen.getAllByRole('checkbox');
		await fireEvent.click(checkboxes[0]); // group checkbox for the filtered Boodschappen group

		expect(
			screen.queryByLabelText(/Also map .* to this category for future imports/)
		).not.toBeInTheDocument();

		const assignInput = screen.getByPlaceholderText('Assign category...');
		await selectCategory(assignInput, 'Eten');

		const applyBtn = screen.getByRole('button', { name: 'Apply' });
		await fireEvent.click(applyBtn);

		await waitFor(() => {
			expect(categorizeSelected).toHaveBeenCalledWith({
				transaction_ids: [1],
				category_id: 10,
			});
		});
		expect(bulkCategorize).not.toHaveBeenCalled();
	});
});

describe('categorizeSelected API function', () => {
	it('calls the correct endpoint', async () => {
		(categorizeSelected as Mock).mockResolvedValue({ updated: 3 });

		const result = await categorizeSelected({
			transaction_ids: [1, 2, 3],
			category_id: 10,
		});

		expect(categorizeSelected).toHaveBeenCalledWith({
			transaction_ids: [1, 2, 3],
			category_id: 10,
		});
		expect(result).toEqual({ updated: 3 });
	});
});
