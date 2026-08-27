from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

# Alias to avoid Pydantic v2 field-name shadowing (field named "date" with default
# None causes Pydantic to resolve the type annotation "date" as None).
DateType = date


# --- Transactions ---


class TransactionOut(BaseModel):
    id: int
    datum: date
    rekening: str
    tegenrekening: Optional[str]
    naam: Optional[str]
    bedrag: float
    valuta: str
    omschrijving: str
    categorie: str
    category_id: Optional[int] = None
    category_name: Optional[str] = None
    merchant_name: Optional[str]
    type: str
    code: str
    has_receipt: bool = False
    is_internal_transfer: bool = False
    is_incidental: bool = False
    incidental_label_id: Optional[int] = None
    created_at: datetime
    offset_total: float = 0.0
    is_offset_income: bool = False

    model_config = {"from_attributes": True}

    @model_validator(mode="wrap")
    @classmethod
    def _populate_category_name(cls, obj, handler):
        instance = handler(obj)
        if hasattr(obj, "category") and obj.category is not None:
            instance.category_name = obj.category.name
        return instance


class TransactionDetail(TransactionOut):
    adres: Optional[str]
    postcode: Optional[str]
    woonplaats: Optional[str]
    valuta_saldo: str
    saldo_voor_boeking: float
    verwerkingsdatum: date
    valutadatum: date
    volgnummer: str
    betalingskenmerk: Optional[str]
    afschriftnummer: str
    receipt: Optional["ReceiptOut"] = None
    line_items: list["LineItemOut"] = []
    offsets: list["TransactionOut"] = []
    offsets_expense: Optional["TransactionOut"] = None


class TransactionListResponse(BaseModel):
    items: list[TransactionOut]
    total: int
    page: int
    per_page: int


class ImportResult(BaseModel):
    imported: int
    skipped_duplicates: int
    updated: int = 0
    categorized: int = 0
    uncategorized: int = 0
    matches: "MatchResult"


class MatchResult(BaseModel):
    auto_linked: int
    pending_confirmation: list["MatchCandidate"]


class MatchCandidate(BaseModel):
    receipt_id: int
    transaction_id: int
    confidence: float
    receipt_merchant: Optional[str]
    transaction_merchant: Optional[str]
    receipt_amount: Optional[float]
    transaction_amount: float


# --- Receipts ---


class ReceiptOut(BaseModel):
    id: int
    transaction_id: Optional[int]
    date: Optional[date]
    total_amount: Optional[float]
    merchant_name: Optional[str]
    image_path: Optional[str]
    match_confidence: Optional[float]
    created_at: datetime

    model_config = {"from_attributes": True}


class ReceiptDetail(ReceiptOut):
    ocr_raw_text: Optional[str]
    line_items: list["LineItemOut"]
    transaction: Optional[TransactionOut] = None


class ReceiptUpdate(BaseModel):
    date: Optional[DateType] = None
    total_amount: Optional[float] = None
    merchant_name: Optional[str] = None


class OcrResult(BaseModel):
    date: Optional[str]
    total_amount: Optional[float]
    merchant_name: Optional[str]
    line_items: list["OcrLineItem"]
    raw_text: str


class OcrLineItem(BaseModel):
    description: str
    amount: float
    quantity: int = 1


class ReceiptCreateResponse(BaseModel):
    id: int
    image_path: str
    ocr_result: OcrResult


# --- Line Items ---


class LineItemOut(BaseModel):
    id: int
    receipt_id: int
    description: str
    amount: float
    quantity: int
    category_id: Optional[int] = None
    category_name: Optional[str] = None
    sort_order: int
    is_remaining: bool = False

    model_config = {"from_attributes": True}

    @model_validator(mode="wrap")
    @classmethod
    def _populate_category_name(cls, obj, handler):
        instance = handler(obj)
        if hasattr(obj, "category") and obj.category is not None:
            instance.category_name = obj.category.name
        return instance


class LineItemCreate(BaseModel):
    description: str
    amount: float
    quantity: int = 1
    category_id: Optional[int] = None
    sort_order: int = 0


class LineItemUpdate(BaseModel):
    description: Optional[str] = None
    amount: Optional[float] = None
    quantity: Optional[int] = None
    category_id: Optional[int] = None
    sort_order: Optional[int] = None


# --- Categories ---


class CategoryOut(BaseModel):
    id: int
    name: str
    parent_id: Optional[int]
    is_fixed: bool
    category_type: str
    children: list["CategoryOut"] = []

    model_config = {"from_attributes": True}


class CategoryCreate(BaseModel):
    name: str
    parent_id: Optional[int] = None
    category_type: str = "expense"
    is_fixed: bool = False


class CategoryUpdate(BaseModel):
    name: Optional[str] = None
    parent_id: Optional[int] = None
    category_type: Optional[str] = None
    is_fixed: Optional[bool] = None


class CategoryMergeCounts(BaseModel):
    transactions: int
    line_items: int
    budget_lines: int
    budget_templates: int
    category_mappings: int
    children: int


# --- Dashboard ---


class DashboardSummary(BaseModel):
    total_income: float
    total_expenses: float
    net: float
    transaction_count: int
    receipts_attached: int
    transfers_out: float = 0.0
    transfers_in: float = 0.0
    transfers_net: float = 0.0
    data_through: Optional[date] = None


class CategorySpending(BaseModel):
    category: str
    category_id: Optional[int] = None
    total: float
    count: int
    has_children: bool = False


class SubcategorySpending(BaseModel):
    category: str
    total: float
    count: int


class SpendingLineItem(BaseModel):
    line_item_id: Optional[int] = None
    description: str
    amount: float
    quantity: int
    category_id: Optional[int] = None
    category_name: Optional[str] = None
    is_remaining: bool
    transaction_id: int
    transaction_date: date
    transaction_merchant: Optional[str]
    transaction_amount: float


class BreadcrumbItem(BaseModel):
    id: int
    name: str


class CategoryLineItemGroup(BaseModel):
    category_id: int
    category_name: str
    total: float
    line_items: list[SpendingLineItem]


class CategoryDetail(BaseModel):
    category_id: int
    category_name: str
    breadcrumb: list[BreadcrumbItem]
    total: float
    # Items categorized on this category itself; child spending lives in groups.
    line_items: list[SpendingLineItem]
    groups: list[CategoryLineItemGroup] = []


class MonthlyTrend(BaseModel):
    month: str
    income: float
    expenses: float
    net: float


# --- Category Mappings ---


class CategoryMappingOut(BaseModel):
    id: int
    bank_category: str
    category_id: int
    category_name: str

    model_config = {"from_attributes": True}


class CategoryMappingCreate(BaseModel):
    bank_category: str
    category_id: int


# --- Budget ---


class BudgetLineOut(BaseModel):
    id: int
    category_id: int
    category_name: str
    category_type: str
    is_fixed: bool
    amount: float
    is_overridden: bool = False
    template_amount: float = 0.0
    balance: float = 0.0

    model_config = {"from_attributes": True}


class BudgetLineCreate(BaseModel):
    category_id: int
    amount: float


class BudgetSummary(BaseModel):
    id: int
    start_date: date
    end_date: date
    line_count: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class BudgetOut(BaseModel):
    id: int
    start_date: date
    end_date: date
    lines: list[BudgetLineOut] = []
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class BudgetCreate(BaseModel):
    start_date: date
    end_date: date
    lines: list[BudgetLineCreate] = []


class BudgetUpdate(BaseModel):
    lines: list[BudgetLineCreate] = []


class BudgetPatch(BaseModel):
    start_date: date | None = None
    end_date: date | None = None


# --- Budget Template ---


class BudgetTemplateLineOut(BaseModel):
    id: int
    category_id: int
    category_name: str
    category_type: str
    is_fixed: bool
    amount: float

    model_config = {"from_attributes": True}


class BudgetTemplateOut(BaseModel):
    lines: list[BudgetTemplateLineOut]
    total_income: float
    total_fixed_expenses: float
    discretionary: float
    total_flexible_expenses: float
    unallocated: float


class BudgetTemplateLineCreate(BaseModel):
    category_id: int
    amount: float


# --- Budget vs Actual ---


class BudgetVsActualLine(BaseModel):
    category_id: int
    category_name: str
    category_type: str
    is_fixed: bool
    budgeted: float
    actual: float
    difference: float
    percentage: float
    balance: float = 0.0


class BudgetVsActualSummary(BaseModel):
    budget_id: int
    start_date: date
    end_date: date
    total_budgeted_income: float
    total_actual_income: float
    total_budgeted_expenses: float
    total_actual_expenses: float
    budgeted_net: float
    actual_net: float
    savings_rate: float
    income_lines: list[BudgetVsActualLine]
    expense_lines: list[BudgetVsActualLine]
    unmapped_expenses: float
    unmapped_income: float


# --- Own Accounts ---


class OwnAccountCreate(BaseModel):
    iban: str = Field(min_length=8, max_length=34)
    name: str = Field(min_length=1, max_length=100)
    account_type: Literal["checking", "savings"]
    starting_balance: Optional[float] = None
    starting_balance_date: Optional[date] = None


class OwnAccountUpdate(BaseModel):
    iban: Optional[str] = Field(default=None, min_length=8, max_length=34)
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    account_type: Optional[Literal["checking", "savings"]] = None
    starting_balance: Optional[float] = None
    starting_balance_date: Optional[date] = None


class OwnAccountOut(BaseModel):
    id: int
    iban: str
    name: str
    account_type: str
    starting_balance: Optional[float]
    starting_balance_date: Optional[date]
    created_at: datetime

    model_config = {"from_attributes": True}


class RecurringPaymentOut(BaseModel):
    id: int
    merchant_pattern: str
    counterparty_iban: Optional[str]
    name: str
    expected_amount: float
    amount_tolerance: float
    cadence: str
    expected_day: Optional[int]
    anchor_date: date
    status: str
    category_id: Optional[int]
    is_income: bool
    created_at: datetime
    updated_at: datetime
    next_expected: Optional[date] = None
    occurrence_count: int = 0
    last_seen: Optional[date] = None

    model_config = {"from_attributes": True}


class RecurringPaymentConfirm(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    category_id: Optional[int] = None


class RecurringPaymentUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    category_id: Optional[int] = None
    expected_amount: Optional[float] = None
    amount_tolerance: Optional[float] = Field(default=None, gt=0)
    status: Optional[Literal["suggested", "confirmed", "dismissed"]] = None


class RecurringPaymentOccurrenceOut(BaseModel):
    id: int
    transaction_id: int
    amount: float
    date: date

    model_config = {"from_attributes": True}


class RescanResult(BaseModel):
    suggested: int
    confirmed: int
    dismissed: int


class RecurringNoticeOut(BaseModel):
    recurring_payment_id: int
    name: str
    type: Literal["amount_changed", "possibly_missed"]
    detail: str
    date: date


class BulkFlagsRequest(BaseModel):
    transaction_ids: list[int] = Field(min_length=1)
    is_incidental: Optional[bool] = None
    is_internal_transfer: Optional[bool] = None
    incidental_label_id: Optional[int] = None

    @model_validator(mode="after")
    def _require_at_least_one_flag(self):
        if (
            self.is_incidental is None
            and self.is_internal_transfer is None
            and self.incidental_label_id is None
        ):
            raise ValueError("At least one of is_incidental, is_internal_transfer, incidental_label_id is required")
        return self


# --- Incidental labels ---


class IncidentalLabelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def _strip_and_check(self):
        stripped = self.name.strip()
        if not stripped:
            raise ValueError("Label name must not be blank")
        self.name = stripped
        return self


class IncidentalLabelOut(BaseModel):
    id: int
    name: str

    model_config = {"from_attributes": True}


class IncidentalLabelSummary(BaseModel):
    id: int
    name: str
    total: float
    count: int
    date_from: Optional[DateType] = None
    date_to: Optional[DateType] = None


class SavingsBalanceOut(BaseModel):
    balance: float
    is_net_only: bool
    account_name: str


class BalancePoint(BaseModel):
    date: date
    balance: float


class CashflowPeriodOut(BaseModel):
    start_date: date
    end_date: date
    label: str


class SavingsCapacityMonth(BaseModel):
    month: str
    partial: bool
    income: float
    expenses_total: float
    expenses_structural: float
    incidental: float
    fixed: float
    flexible: float
    uncategorized: float
    net_raw: float
    net_structural: float


class SavingsCapacitySummary(BaseModel):
    months: list[SavingsCapacityMonth]
    trailing_3_raw: Optional[float]
    trailing_3_structural: Optional[float]
    trailing_6_raw: Optional[float]
    trailing_6_structural: Optional[float]
    current_month_projection: Optional[float] = None


class CashflowCalendarItemOut(BaseModel):
    recurring_payment_id: int
    name: str
    amount: float
    is_income: bool
    is_salary: bool


class CashflowCalendarDayOut(BaseModel):
    date: date
    items: list[CashflowCalendarItemOut]


class CashflowCalendarOut(BaseModel):
    month: str
    days: list[CashflowCalendarDayOut]


class CashflowReturnTransferOut(BaseModel):
    date: date
    amount: float
    cadence: str  # "monthly" | "four_weekly"
    covers: list[str]


class CashflowAdviceOut(BaseModel):
    salary_confirmed: bool
    message: Optional[str] = None
    payday: Optional[date] = None
    next_payday: Optional[date] = None
    sweep_amount: Optional[float] = None
    keep_in_checking: float = 0.0
    standing_buffer: float = 0.0
    buffer_pct: float
    return_transfers: list[CashflowReturnTransferOut] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class CashflowSettingsOut(BaseModel):
    buffer_pct: float


class CashflowSettingsUpdate(BaseModel):
    buffer_pct: float = Field(ge=0, le=100)
