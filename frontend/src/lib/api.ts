const BASE = '';

async function request<T>(path: string, options?: RequestInit): Promise<T> {
	const res = await fetch(`${BASE}${path}`, options);
	if (res.status === 401) {
		window.location.href = '/login';
		throw new Error('Not authenticated');
	}
	if (!res.ok) {
		const text = await res.text();
		throw new Error(`${res.status}: ${text}`);
	}
	return res.json();
}

export async function logout(): Promise<void> {
	await fetch('/api/auth/logout', { method: 'POST' });
}

export interface Transaction {
	id: number;
	datum: string;
	rekening: string;
	tegenrekening: string | null;
	naam: string | null;
	bedrag: number;
	valuta: string;
	omschrijving: string;
	categorie: string;
	category_id: number | null;
	category_name: string | null;
	merchant_name: string | null;
	type: string;
	code: string;
	has_receipt: boolean;
	created_at: string;
}

export interface TransactionDetail extends Transaction {
	adres: string | null;
	postcode: string | null;
	woonplaats: string | null;
	valuta_saldo: string;
	saldo_voor_boeking: number;
	verwerkingsdatum: string;
	valutadatum: string;
	volgnummer: string;
	betalingskenmerk: string | null;
	afschriftnummer: string;
	receipt: Receipt | null;
	line_items: LineItem[];
	offsets: Transaction[];
	offsets_expense: Transaction | null;
}

export interface TransactionListResponse {
	items: Transaction[];
	total: number;
	page: number;
	per_page: number;
}

export interface Receipt {
	id: number;
	transaction_id: number | null;
	date: string | null;
	total_amount: number | null;
	merchant_name: string | null;
	image_path: string | null;
	match_confidence: number | null;
	created_at: string;
}

export interface MatchCandidate {
	receipt_id: number;
	transaction_id: number;
	confidence: number;
	receipt_merchant: string | null;
	transaction_merchant: string | null;
	receipt_amount: number | null;
	transaction_amount: number;
}

export interface ImportResult {
	imported: number;
	skipped_duplicates: number;
	updated: number;
	matches: {
		auto_linked: number;
		pending_confirmation: MatchCandidate[];
	};
}

export async function importCsv(file: File, updateDuplicates: boolean = false): Promise<ImportResult> {
	const form = new FormData();
	form.append('file', file);
	const qs = updateDuplicates ? '?update_duplicates=true' : '';
	return request(`/api/transactions/import${qs}`, { method: 'POST', body: form });
}

export async function getTransactions(params: {
	page?: number;
	per_page?: number;
	date_from?: string;
	date_to?: string;
	category_id?: number;
	search?: string;
	has_receipt?: boolean;
} = {}): Promise<TransactionListResponse> {
	const qs = new URLSearchParams();
	for (const [k, v] of Object.entries(params)) {
		if (v !== undefined && v !== null && v !== '') qs.set(k, String(v));
	}
	return request(`/api/transactions?${qs}`);
}

export async function getTransaction(id: number): Promise<TransactionDetail> {
	return request(`/api/transactions/${id}`);
}

export async function updateTransaction(id: number, data: { category_id?: number | null }): Promise<Transaction> {
	return request(`/api/transactions/${id}`, {
		method: 'PATCH',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(data),
	});
}

export async function splitTransactionReceipt(transactionId: number): Promise<{ receipt_id: number }> {
	return request(`/api/transactions/${transactionId}/split-receipt`, { method: 'POST' });
}

export async function linkOffset(expenseId: number, incomeId: number): Promise<void> {
	return request(`/api/transactions/${expenseId}/offsets/${incomeId}`, { method: 'POST' });
}

export async function unlinkOffset(expenseId: number, incomeId: number): Promise<void> {
	return request(`/api/transactions/${expenseId}/offsets/${incomeId}`, { method: 'DELETE' });
}

export async function saveTransactionLineItems(txId: number, items: LineItemCreate[]): Promise<LineItem[]> {
	return request(`/api/transactions/${txId}/line-items`, {
		method: 'PUT',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(items),
	});
}

export function formatEuro(amount: number): string {
	return new Intl.NumberFormat('nl-NL', { style: 'currency', currency: 'EUR' }).format(amount);
}

export function formatDate(dateStr: string): string {
	return new Date(dateStr).toLocaleDateString('nl-NL', {
		day: '2-digit',
		month: '2-digit',
		year: 'numeric'
	});
}

// --- Receipts ---

export interface ReceiptDetail extends Receipt {
	ocr_raw_text: string | null;
	line_items: LineItem[];
	transaction: Transaction | null;
}

export interface LineItem {
	id: number;
	receipt_id: number;
	description: string;
	amount: number;
	quantity: number;
	category_id: number | null;
	category_name: string | null;
	sort_order: number;
	is_remaining: boolean;
}

export interface LineItemCreate {
	description: string;
	amount: number;
	quantity?: number;
	category_id?: number | null;
	sort_order?: number;
}

export interface OcrResult {
	date: string | null;
	total_amount: number | null;
	merchant_name: string | null;
	line_items: { description: string; amount: number; quantity: number }[];
	raw_text: string;
}

export interface ReceiptCreateResponse {
	id: number;
	image_path: string;
	ocr_result: OcrResult;
}

export async function uploadReceipt(file: File, preset?: string): Promise<ReceiptCreateResponse> {
	const form = new FormData();
	form.append('file', file);
	if (preset) {
		form.append('preset', preset);
	}
	return request('/api/receipts', { method: 'POST', body: form });
}

export async function getReceiptPresets(): Promise<string[]> {
	return request('/api/receipts/presets');
}

export async function getReceipts(params: {
	unmatched?: boolean;
	date_from?: string;
	date_to?: string;
} = {}): Promise<Receipt[]> {
	const qs = new URLSearchParams();
	for (const [k, v] of Object.entries(params)) {
		if (v !== undefined && v !== null && v !== '') qs.set(k, String(v));
	}
	return request(`/api/receipts?${qs}`);
}

export async function getReceipt(id: number): Promise<ReceiptDetail> {
	return request(`/api/receipts/${id}`);
}

export async function updateReceipt(id: number, data: {
	date?: string;
	total_amount?: number;
	merchant_name?: string;
}): Promise<Receipt> {
	return request(`/api/receipts/${id}`, {
		method: 'PATCH',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(data),
	});
}

export async function deleteReceipt(id: number): Promise<void> {
	return request(`/api/receipts/${id}`, { method: 'DELETE' });
}

export async function linkReceipt(receiptId: number, transactionId: number): Promise<Receipt> {
	return request(`/api/receipts/${receiptId}/link/${transactionId}`, { method: 'POST' });
}

export async function unlinkReceipt(receiptId: number): Promise<Receipt> {
	return request(`/api/receipts/${receiptId}/unlink`, { method: 'POST' });
}

// --- Line Items ---

export async function getLineItems(receiptId: number): Promise<LineItem[]> {
	return request(`/api/receipts/${receiptId}/line-items`);
}

export async function createLineItem(receiptId: number, data: LineItemCreate): Promise<LineItem> {
	return request(`/api/receipts/${receiptId}/line-items`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(data),
	});
}

export async function bulkReplaceLineItems(receiptId: number, items: LineItemCreate[]): Promise<LineItem[]> {
	return request(`/api/receipts/${receiptId}/line-items`, {
		method: 'PUT',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(items),
	});
}

export async function updateLineItem(id: number, data: { category_id?: number | null; description?: string; amount?: number; quantity?: number; sort_order?: number }): Promise<LineItem> {
	return request(`/api/line-items/${id}`, {
		method: 'PATCH',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(data),
	});
}

export async function deleteLineItem(id: number): Promise<void> {
	return request(`/api/line-items/${id}`, { method: 'DELETE' });
}

export async function triggerMatching(): Promise<MatchCandidate[]> {
	return request('/api/receipts/match', { method: 'POST' });
}

export function imageUrl(path: string): string {
	return `${BASE}${path}`;
}

// --- Dashboard ---

export interface DashboardSummary {
	total_income: number;
	total_expenses: number;
	net: number;
	transaction_count: number;
	receipts_attached: number;
}

export interface CategorySpending {
	category: string;
	category_id: number | null;
	total: number;
	count: number;
	has_children: boolean;
}

export interface SubcategorySpending {
	category: string;
	total: number;
	count: number;
}

export interface MonthlyTrend {
	month: string;
	income: number;
	expenses: number;
	net: number;
}

export async function getDashboardSummary(params: {
	date_from?: string;
	date_to?: string;
} = {}): Promise<DashboardSummary> {
	const qs = new URLSearchParams();
	for (const [k, v] of Object.entries(params)) {
		if (v !== undefined && v !== null && v !== '') qs.set(k, String(v));
	}
	return request(`/api/dashboard/summary?${qs}`);
}

export async function getByCategory(params: {
	date_from?: string;
	date_to?: string;
} = {}): Promise<CategorySpending[]> {
	const qs = new URLSearchParams();
	for (const [k, v] of Object.entries(params)) {
		if (v !== undefined && v !== null && v !== '') qs.set(k, String(v));
	}
	return request(`/api/dashboard/by-category?${qs}`);
}

export interface SpendingLineItem {
	line_item_id: number;
	description: string;
	amount: number;
	quantity: number;
	category_id: number | null;
	category_name: string | null;
	is_remaining: boolean;
	transaction_id: number;
	transaction_date: string;
	transaction_merchant: string | null;
	transaction_amount: number;
}

export interface BreadcrumbItem {
	id: number;
	name: string;
}

export interface CategoryDetail {
	category_id: number;
	category_name: string;
	breadcrumb: BreadcrumbItem[];
	total: number;
	line_items: SpendingLineItem[];
}

export async function getCategoryDetail(categoryId: number, params: {
	date_from?: string;
	date_to?: string;
} = {}): Promise<CategoryDetail> {
	const qs = new URLSearchParams();
	for (const [k, v] of Object.entries(params)) {
		if (v !== undefined && v !== null && v !== '') qs.set(k, String(v));
	}
	return request(`/api/dashboard/category/${categoryId}/line-items?${qs}`);
}

export async function getCategoryChildren(categoryId: number, params: {
	date_from?: string;
	date_to?: string;
} = {}): Promise<CategorySpending[]> {
	const qs = new URLSearchParams();
	for (const [k, v] of Object.entries(params)) {
		if (v !== undefined && v !== null && v !== '') qs.set(k, String(v));
	}
	return request(`/api/dashboard/by-category-children/${categoryId}?${qs}`);
}

export async function getBySubcategory(params: {
	categorie?: string;
	date_from?: string;
	date_to?: string;
} = {}): Promise<SubcategorySpending[]> {
	const qs = new URLSearchParams();
	for (const [k, v] of Object.entries(params)) {
		if (v !== undefined && v !== null && v !== '') qs.set(k, String(v));
	}
	return request(`/api/dashboard/by-subcategory?${qs}`);
}

export async function getMonthlyTrend(months: number = 6): Promise<MonthlyTrend[]> {
	return request(`/api/dashboard/monthly-trend?months=${months}`);
}

// --- Categories ---

export interface Category {
	id: number;
	name: string;
	parent_id: number | null;
	is_fixed: boolean;
	category_type: string;
	children: Category[];
}

export async function getCategories(): Promise<Category[]> {
	return request('/api/categories');
}

export async function createCategory(name: string, parent_id?: number, category_type: string = 'expense'): Promise<Category> {
	return request('/api/categories', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ name, parent_id: parent_id ?? null, category_type }),
	});
}

export async function updateCategory(id: number, data: { name: string; parent_id?: number | null; category_type?: string; is_fixed?: boolean }): Promise<Category> {
	return request(`/api/categories/${id}`, {
		method: 'PATCH',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(data),
	});
}

export async function deleteCategory(id: number): Promise<void> {
	return request(`/api/categories/${id}`, { method: 'DELETE' });
}

// --- Category Mappings ---

export interface CategoryMapping {
	id: number;
	bank_category: string;
	category_id: number;
	category_name: string;
}

export async function getCategoryMappings(): Promise<CategoryMapping[]> {
	return request('/api/category-mappings');
}

// --- Uncategorized ---

export interface UncategorizedTransaction {
	id: number;
	datum: string;
	bedrag: number;
	merchant_name: string | null;
	naam: string | null;
	omschrijving: string;
}

export interface UncategorizedGroup {
	bank_category: string;
	count: number;
	total: number;
	has_mapping: boolean;
	transactions: UncategorizedTransaction[];
}

export async function getUncategorized(): Promise<UncategorizedGroup[]> {
	return request('/api/uncategorized');
}

export async function bulkCategorize(data: {
	bank_category: string;
	category_id: number;
	save_mapping: boolean;
}): Promise<{ updated: number }> {
	return request('/api/uncategorized/bulk-categorize', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(data),
	});
}

export async function categorizeSelected(data: {
	transaction_ids: number[];
	category_id: number;
}): Promise<{ updated: number }> {
	return request('/api/uncategorized/categorize-selected', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(data),
	});
}

export async function getUnmappedCategories(): Promise<string[]> {
	return request('/api/category-mappings/unmapped');
}

export async function createCategoryMapping(data: { bank_category: string; category_id: number }): Promise<CategoryMapping> {
	return request('/api/category-mappings', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(data),
	});
}

export async function updateCategoryMapping(id: number, data: { bank_category: string; category_id: number }): Promise<CategoryMapping> {
	return request(`/api/category-mappings/${id}`, {
		method: 'PUT',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(data),
	});
}

export async function deleteCategoryMapping(id: number): Promise<void> {
	return request(`/api/category-mappings/${id}`, { method: 'DELETE' });
}

// --- Budgets ---

export interface BudgetLine {
	id: number;
	category_id: number;
	category_name: string;
	category_type: string;
	is_fixed: boolean;
	amount: number;
	is_overridden: boolean;
	template_amount: number;
	balance: number;
}

export interface BudgetSummary {
	id: number;
	start_date: string;
	end_date: string;
	line_count: number;
	created_at: string;
	updated_at: string;
}

export interface Budget {
	id: number;
	start_date: string;
	end_date: string;
	lines: BudgetLine[];
	created_at: string;
	updated_at: string;
}

export interface BudgetVsActualLine {
	category_id: number;
	category_name: string;
	category_type: string;
	is_fixed: boolean;
	budgeted: number;
	actual: number;
	difference: number;
	percentage: number;
	balance: number;
}

export interface BudgetVsActualSummary {
	budget_id: number;
	start_date: string;
	end_date: string;
	total_budgeted_income: number;
	total_actual_income: number;
	total_budgeted_expenses: number;
	total_actual_expenses: number;
	budgeted_net: number;
	actual_net: number;
	savings_rate: number;
	income_lines: BudgetVsActualLine[];
	expense_lines: BudgetVsActualLine[];
	unmapped_expenses: number;
	unmapped_income: number;
}

export async function getBudgets(): Promise<BudgetSummary[]> {
	return request('/api/budgets');
}

export async function getBudget(budgetId: number): Promise<Budget> {
	return request(`/api/budgets/${budgetId}`);
}

export async function createBudget(data: { start_date: string; end_date: string }): Promise<Budget> {
	return request('/api/budgets', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(data),
	});
}

export async function updateBudget(budgetId: number, data: { lines: { category_id: number; amount: number }[] }, updateTemplate: boolean = false): Promise<Budget> {
	const qs = updateTemplate ? '?update_template=true' : '';
	return request(`/api/budgets/${budgetId}${qs}`, {
		method: 'PUT',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(data),
	});
}

export async function patchBudget(budgetId: number, data: { start_date?: string; end_date?: string }): Promise<Budget> {
	return request(`/api/budgets/${budgetId}`, {
		method: 'PATCH',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(data),
	});
}

export async function deleteBudget(budgetId: number): Promise<void> {
	return request(`/api/budgets/${budgetId}`, { method: 'DELETE' });
}

export async function getBudgetVsActual(budgetId: number): Promise<BudgetVsActualSummary> {
	return request(`/api/dashboard/budget-vs-actual/${budgetId}`);
}

export function formatPeriodLabel(startDate: string, endDate: string): string {
	const start = new Date(startDate);
	const end = new Date(endDate);
	const fmt = (d: Date) => d.toLocaleDateString('nl-NL', { day: 'numeric', month: 'short' });
	const yearStr = end.toLocaleDateString('nl-NL', { year: 'numeric' });
	return `${fmt(start)} - ${fmt(end)} ${yearStr}`;
}

// --- Budget Template ---

export interface BudgetTemplateLine {
	id: number;
	category_id: number;
	category_name: string;
	category_type: string;
	is_fixed: boolean;
	amount: number;
}

export interface BudgetTemplate {
	lines: BudgetTemplateLine[];
	total_income: number;
	total_fixed_expenses: number;
	discretionary: number;
	total_flexible_expenses: number;
	unallocated: number;
}

export async function getBudgetTemplate(): Promise<BudgetTemplate> {
	return request('/api/budget-template');
}

export async function replaceBudgetTemplate(lines: { category_id: number; amount: number }[]): Promise<BudgetTemplate> {
	return request('/api/budget-template', {
		method: 'PUT',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(lines),
	});
}

// --- Sync ---

export interface ImportConflict {
	code: string;
	severity: 'soft' | 'hard';
	message: string;
}

export interface TransactionPreview {
	import_hash: string;
	datum: string;
	bedrag: number;
	merchant_name: string | null;
	omschrijving: string;
}

export interface TransactionUpdatePreview {
	import_hash: string;
	datum: string;
	bedrag: number;
	omschrijving: string;
	old_category_name: string | null;
	new_category_name: string | null;
	old_merchant_name: string | null;
	new_merchant_name: string | null;
}

export interface ImportPreview {
	will_add_categories: number;
	will_add_category_mappings: number;
	will_add_budgets: number;
	will_add_budget_lines: number;
	will_update_budget_lines: number;
	will_add_budget_templates: number;
	will_add_transactions: number;
	will_update_transactions: number;
	will_skip_transactions: number;
	will_add_offsets: number;
	add_categories: string[];
	add_transactions: TransactionPreview[];
	skip_transactions: TransactionPreview[];
	update_transactions: TransactionUpdatePreview[];
	sample_truncated_at: number;
	soft_conflicts: ImportConflict[];
	hard_conflicts: ImportConflict[];
}

export interface ImportResultResponse {
	preview: ImportPreview;
	committed: boolean;
	backup_path: string | null;
}

export async function downloadSyncExport(since?: string): Promise<Blob> {
	const qs = since ? `?since=${encodeURIComponent(since)}` : '';
	const res = await fetch(`/api/sync/export${qs}`, { credentials: 'include' });
	if (!res.ok) throw new Error(`Export failed: ${res.status}`);
	return res.blob();
}

export async function previewSyncImport(file: File): Promise<ImportResultResponse> {
	const form = new FormData();
	form.append('file', file);
	return request('/api/sync/import?dry_run=true', { method: 'POST', body: form });
}

export async function commitSyncImport(
	file: File,
	updateDuplicates: boolean,
): Promise<ImportResultResponse> {
	const form = new FormData();
	form.append('file', file);
	const qs = `?dry_run=false&update_duplicates=${updateDuplicates}`;
	return request(`/api/sync/import${qs}`, { method: 'POST', body: form });
}
