"""Internal-transfer detection between the user's own accounts.

Transactions whose counterparty IBAN matches an OwnAccount are transfers,
not income or expenses, and are excluded from all analytics."""
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import OwnAccount, Transaction


def normalize_iban(value: str) -> str:
    return value.replace(" ", "").upper()


def own_ibans(db: Session) -> set[str]:
    accounts = db.execute(select(OwnAccount)).scalars().all()
    return {normalize_iban(a.iban) for a in accounts}


def is_internal(tx: Transaction, ibans: set[str]) -> bool:
    if not tx.tegenrekening:
        return False
    return normalize_iban(tx.tegenrekening) in ibans


def backfill_internal_transfers(db: Session) -> int:
    """Re-derive the flag for every transaction from the current own-account
    set. Rows the user overrode manually are never touched. Does not commit."""
    ibans = own_ibans(db)
    changed = 0
    txs = db.execute(
        select(Transaction).where(Transaction.is_internal_transfer_manual.is_(False))
    ).scalars().all()
    for tx in txs:
        flag = is_internal(tx, ibans)
        if tx.is_internal_transfer != flag:
            tx.is_internal_transfer = flag
            changed += 1
    return changed


@dataclass(frozen=True)
class SavingsBalanceResult:
    balance: float
    is_net_only: bool  # True when no starting balance is configured
    account_name: str


def savings_balance(db: Session) -> SavingsBalanceResult | None:
    """Inferred savings balance: starting balance plus net transfers from
    checking since the starting-balance date. None when no savings account
    is configured."""
    savings = db.execute(
        select(OwnAccount).where(OwnAccount.account_type == "savings")
    ).scalars().first()
    if savings is None:
        return None

    savings_iban = normalize_iban(savings.iban)
    query = select(Transaction).where(Transaction.is_internal_transfer.is_(True))
    if savings.starting_balance_date is not None:
        query = query.where(Transaction.datum >= savings.starting_balance_date)

    net_in = 0.0
    for tx in db.execute(query).scalars().all():
        if tx.tegenrekening and normalize_iban(tx.tegenrekening) == savings_iban:
            # Negative bedrag on checking means money arrived in savings.
            net_in += -tx.bedrag

    has_start = savings.starting_balance is not None
    base = savings.starting_balance if has_start else 0.0
    return SavingsBalanceResult(
        balance=round(base + net_in, 2),
        is_net_only=not has_start,
        account_name=savings.name,
    )
