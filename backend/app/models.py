from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    category_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("categories.id"))

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
        foreign_keys=[expense_transaction_id], overlaps="offsets"
    )
    income_transaction: Mapped["Transaction"] = relationship(
        foreign_keys=[income_transaction_id], overlaps="offset_of"
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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

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
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    parent_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("categories.id"))
    is_fixed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    category_type: Mapped[str] = mapped_column(String(10), default="expense", nullable=False)

    children: Mapped[list["Category"]] = relationship(back_populates="parent")
    parent: Mapped["Category | None"] = relationship(
        back_populates="children", remote_side=[id]
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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
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
