from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import require_auth
from ..database import get_db
from ..models import OwnAccount
from ..schemas import OwnAccountCreate, OwnAccountOut, OwnAccountUpdate
from ..services.transfers import backfill_internal_transfers, normalize_iban

router = APIRouter(
    prefix="/api/own-accounts", tags=["own-accounts"], dependencies=[Depends(require_auth)]
)


@router.get("", response_model=list[OwnAccountOut])
def list_own_accounts(db: Session = Depends(get_db)):
    return db.execute(select(OwnAccount).order_by(OwnAccount.id)).scalars().all()


@router.post("", response_model=OwnAccountOut)
def create_own_account(data: OwnAccountCreate, db: Session = Depends(get_db)):
    iban = normalize_iban(data.iban)
    existing = db.execute(
        select(OwnAccount).where(OwnAccount.iban == iban)
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="An account with this IBAN already exists")

    account = OwnAccount(
        iban=iban,
        name=data.name,
        account_type=data.account_type,
        starting_balance=data.starting_balance,
        starting_balance_date=data.starting_balance_date,
    )
    db.add(account)
    db.flush()
    backfill_internal_transfers(db)
    db.commit()
    db.refresh(account)
    return account


@router.patch("/{account_id}", response_model=OwnAccountOut)
def update_own_account(account_id: int, data: OwnAccountUpdate, db: Session = Depends(get_db)):
    account = db.get(OwnAccount, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    iban_changed = False
    updates = data.model_dump(exclude_unset=True)
    if "iban" in updates and updates["iban"] is not None:
        updates["iban"] = normalize_iban(updates["iban"])
        iban_changed = updates["iban"] != account.iban
        if iban_changed:
            existing = db.execute(
                select(OwnAccount).where(
                    OwnAccount.iban == updates["iban"], OwnAccount.id != account_id
                )
            ).scalar_one_or_none()
            if existing:
                raise HTTPException(
                    status_code=409, detail="An account with this IBAN already exists"
                )
    for key, value in updates.items():
        setattr(account, key, value)

    if iban_changed:
        db.flush()
        backfill_internal_transfers(db)
    db.commit()
    db.refresh(account)
    return account


@router.delete("/{account_id}")
def delete_own_account(account_id: int, db: Session = Depends(get_db)):
    account = db.get(OwnAccount, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    db.delete(account)
    db.flush()
    backfill_internal_transfers(db)
    db.commit()
    return {"ok": True}
