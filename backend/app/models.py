from datetime import date, datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    datum: Mapped[date] = mapped_column(Date, nullable=False)
    rekening: Mapped[str] = mapped_column(String(34), nullable=False)
    tegenrekening: Mapped[str | None] = mapped_column(String(34))
    naam: Mapped[str | None] = mapped_column(String(255))
    adres: Mapped[str | None] = mapped_column(String(255))
    postcode: Mapped[str | None] = mapped_column(String(10))
    woonplaats: Mapped[str | None] = mapped_column(String(100))
    valuta_saldo: Mapped[str] = mapped_column(String(3), nullable=False)
    saldo_voor_boeking: Mapped[float] = mapped_column(Float, nullable=False)
    valuta: Mapped[str] = mapped_column(String(3), nullable=False)
    bedrag: Mapped[float] = mapped_column(Float, nullable=False)
    verwerkingsdatum: Mapped[date] = mapped_column(Date, nullable=False)
    valutadatum: Mapped[date] = mapped_column(Date, nullable=False)
    code: Mapped[str] = mapped_column(String(10), nullable=False)
    type: Mapped[str] = mapped_column(String(10), nullable=False)
    volgnummer: Mapped[str] = mapped_column(String(20), nullable=False)
    betalingskenmerk: Mapped[str | None] = mapped_column(String(255))
    omschrijving: Mapped[str] = mapped_column(Text, nullable=False)
    afschriftnummer: Mapped[str] = mapped_column(String(20), nullable=False)
    categorie: Mapped[str] = mapped_column(String(100), nullable=False)
    merchant_name: Mapped[str | None] = mapped_column(String(255))
    import_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow, nullable=False
    )
    category_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("categories.id"))
    is_internal_transfer: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_internal_transfer_manual: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_incidental: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    incidental_label_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("incidental_labels.id")
    )

    receipt: Mapped["Receipt | None"] = relationship(back_populates="transaction")
    category: Mapped["Category | None"] = relationship(foreign_keys=[category_id])

    # Offsets: TransactionOffset rows where this tx is the expense
    offset_links: Mapped[list["TransactionOffset"]] = relationship(
        foreign_keys="TransactionOffset.expense_transaction_id",
        cascade="all, delete-orphan",
    )
    # If this income transaction is an offset for an expense
    offset_of_link: Mapped["TransactionOffset | None"] = relationship(
        foreign_keys="TransactionOffset.income_transaction_id",
        uselist=False,
    )


class TransactionOffset(Base):
    __tablename__ = "transaction_offsets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    expense_transaction_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("transactions.id"), nullable=False
    )
    income_transaction_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("transactions.id"), nullable=False, unique=True
    )

    expense_transaction: Mapped["Transaction"] = relationship(
        foreign_keys=[expense_transaction_id], overlaps="offset_links"
    )
    income_transaction: Mapped["Transaction"] = relationship(
        foreign_keys=[income_transaction_id], overlaps="offset_of_link"
    )


class Receipt(Base):
    __tablename__ = "receipts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    transaction_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("transactions.id"), unique=True
    )
    date: Mapped[date | None] = mapped_column(Date, nullable=True)
    total_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    merchant_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    image_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    ocr_raw_text: Mapped[str | None] = mapped_column(Text)
    match_confidence: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    transaction: Mapped["Transaction | None"] = relationship(back_populates="receipt")
    line_items: Mapped[list["LineItem"]] = relationship(
        back_populates="receipt", cascade="all, delete-orphan"
    )


class LineItem(Base):
    __tablename__ = "line_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    receipt_id: Mapped[int] = mapped_column(Integer, ForeignKey("receipts.id"), nullable=False)
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    category_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("categories.id"))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_remaining: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    receipt: Mapped["Receipt"] = relationship(back_populates="line_items")
    category: Mapped["Category | None"] = relationship(foreign_keys=[category_id])


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    parent_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("categories.id"))
    is_fixed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    category_type: Mapped[str] = mapped_column(String(10), default="expense", nullable=False)

    children: Mapped[list["Category"]] = relationship(back_populates="parent")
    parent: Mapped["Category | None"] = relationship(
        back_populates="children", remote_side=[id]
    )

    # Names are unique per parent, not globally (two categories named "Overig"
    # under different parents are allowed). NOTE: SQLite treats NULL as
    # distinct from every other value in a unique constraint, so root-level
    # categories (parent_id IS NULL) are NOT constrained by the DB here; root
    # sibling uniqueness is enforced in the application layer (see
    # routers/categories.py create/update, and services/category_merge.py).
    __table_args__ = (
        UniqueConstraint("parent_id", "name", name="uq_category_parent_name"),
    )


class CategoryMapping(Base):
    __tablename__ = "category_mappings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bank_category: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    category_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("categories.id"), nullable=False
    )

    category: Mapped["Category"] = relationship()


class Budget(Base):
    __tablename__ = "budgets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=datetime.utcnow
    )

    lines: Mapped[list["BudgetLine"]] = relationship(
        back_populates="budget", cascade="all, delete-orphan"
    )

    __table_args__ = (UniqueConstraint("start_date", name="uq_budget_start_date"),)


class BudgetLine(Base):
    __tablename__ = "budget_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    budget_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("budgets.id"), nullable=False
    )
    category_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("categories.id"), nullable=False
    )
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    # "manual" | "recurring" | "allocation": non-manual rows are
    # system-maintained by services/budget_derivation.py and read-only
    # for the user.
    source: Mapped[str] = mapped_column(String(20), default="manual", nullable=False)

    budget: Mapped["Budget"] = relationship(back_populates="lines")
    category: Mapped["Category"] = relationship()

    __table_args__ = (
        UniqueConstraint("budget_id", "category_id", name="uq_budget_line_category"),
    )


class BudgetTemplate(Base):
    __tablename__ = "budget_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    category_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("categories.id"), unique=True, nullable=False
    )
    amount: Mapped[float] = mapped_column(Float, nullable=False)

    category: Mapped["Category"] = relationship()


class PasskeyCredential(Base):
    __tablename__ = "passkey_credentials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    credential_id: Mapped[bytes] = mapped_column(LargeBinary, unique=True, nullable=False)
    public_key: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    sign_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    name: Mapped[str] = mapped_column(String(255), default="My Passkey", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class RevokedToken(Base):
    __tablename__ = "revoked_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    jti: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class WebAuthnChallenge(Base):
    __tablename__ = "webauthn_challenges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    challenge: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)


class ImportedExport(Base):
    __tablename__ = "imported_exports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    export_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    imported_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    transactions_added: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    transactions_updated: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    categories_added: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class SyncEvent(Base):
    """Append-only log of mutations that need to propagate via the sync feature.

    Records renames/deletes that the additive sync merge cannot infer from
    natural keys alone. Each event has a UUID so applying twice is a no-op.
    """
    __tablename__ = "sync_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, nullable=False, index=True
    )


class OwnAccount(Base):
    """A bank account owned by the user. Transactions whose counterparty
    IBAN matches an own account are internal transfers, not income/expenses."""
    __tablename__ = "own_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    iban: Mapped[str] = mapped_column(String(34), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    account_type: Mapped[str] = mapped_column(String(10), nullable=False)  # "checking" | "savings"
    starting_balance: Mapped[float | None] = mapped_column(Float)
    starting_balance_date: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class AllocationBucket(Base):
    """A configured destination for part of each salary (e.g. long-term
    savings, investing). fixed buckets take a set euro amount; percent
    buckets take a share of what remains after bills and fixed buckets.
    Plan-only: nothing is tracked against buckets yet."""
    __tablename__ = "allocation_buckets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    rule_type: Mapped[str] = mapped_column(String(10), nullable=False)  # "fixed" | "percent"
    value: Mapped[float] = mapped_column(Float, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class IncidentalLabel(Base):
    """Groups related one-off transactions across categories, e.g. a holiday
    or a house move, so incidental spending can be explained per event."""
    __tablename__ = "incidental_labels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class RecurringPayment(Base):
    """A detected or confirmed recurring payment pattern (subscription, vaste
    last, or recurring income like salary). Suggested rows are refreshed in
    place by the detector on every run; confirmed/dismissed rows are never
    touched by the detector."""
    __tablename__ = "recurring_payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Stable composite identity used by the detector to refresh a suggested
    # row in place across reruns: "{base_key}|{income|expense}|{cluster
    # index}". Empty for rows created before amount clustering existed (or
    # created directly, e.g. in tests); `_row_key` falls back to
    # "{base_key}|{direction}|0" for those.
    group_key: Mapped[str] = mapped_column(String(400), default="", nullable=False)
    merchant_pattern: Mapped[str] = mapped_column(String(255), nullable=False)
    counterparty_iban: Mapped[str | None] = mapped_column(String(34))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    expected_amount: Mapped[float] = mapped_column(Float, nullable=False)
    amount_tolerance: Mapped[float] = mapped_column(Float, default=0.15, nullable=False)
    cadence: Mapped[str] = mapped_column(String(20), nullable=False)  # monthly | four_weekly | yearly
    expected_day: Mapped[int | None] = mapped_column(Integer)
    anchor_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(
        String(10), default="suggested", nullable=False
    )  # suggested | confirmed | dismissed
    category_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("categories.id"))
    is_income: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow, nullable=False
    )

    category: Mapped["Category | None"] = relationship(foreign_keys=[category_id])
    occurrences: Mapped[list["RecurringPaymentOccurrence"]] = relationship(
        back_populates="recurring_payment", cascade="all, delete-orphan"
    )


class RecurringPaymentOccurrence(Base):
    """One matched transaction for a recurring payment. Kept separate from
    Transaction so a detector re-run can rebuild occurrences without
    touching transaction rows."""
    __tablename__ = "recurring_payment_occurrences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    recurring_payment_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("recurring_payments.id"), nullable=False
    )
    transaction_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("transactions.id"), nullable=False, unique=True
    )
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)

    recurring_payment: Mapped["RecurringPayment"] = relationship(back_populates="occurrences")
    transaction: Mapped["Transaction"] = relationship()


class AppSetting(Base):
    """Tiny key-value settings store. Currently holds only `buffer_pct` (the
    cash-flow advisor's sweep buffer percentage), but kept generic so future
    single-value settings don't each need their own table/migration."""
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(String(255), nullable=False)
