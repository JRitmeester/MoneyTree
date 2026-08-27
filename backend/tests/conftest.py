import os
import uuid

# Set config env vars BEFORE any app imports (config.py validates at import time)
os.environ["JWT_SECRET"] = "test-secret-that-is-at-least-32-characters-long"
os.environ["AUTH_PASSWORD_HASH"] = ""

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import create_token, require_auth
from app.database import get_db
from app.main import app
from app.models import Base, Category, Transaction


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine)
    session = TestSession()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def client(db: Session):
    def _override_db():
        try:
            yield db
        finally:
            pass

    def _override_auth():
        return "test-user"

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[require_auth] = _override_auth

    token = create_token("test-user")

    with TestClient(app, raise_server_exceptions=False, cookies={"auth_token": token}) as c:
        yield c

    app.dependency_overrides.clear()


def make_transaction(
    db: Session,
    *,
    bedrag: float = -10.0,
    categorie: str = "Boodschappen",
    category_id: int | None = None,
    naam: str | None = "Test Store",
    merchant_name: str | None = None,
    omschrijving: str = "Test transaction",
    datum: date = date(2025, 1, 15),
    tegenrekening: str | None = None,
    saldo_voor_boeking: float = 1000.0,
    volgnummer: str = "001",
    is_incidental: bool = False,
) -> Transaction:
    tx = Transaction(
        datum=datum,
        rekening="NL00TEST0000000001",
        tegenrekening=tegenrekening,
        naam=naam,
        valuta_saldo="EUR",
        saldo_voor_boeking=saldo_voor_boeking,
        valuta="EUR",
        bedrag=bedrag,
        verwerkingsdatum=datum,
        valutadatum=datum,
        code="GT",
        type="BET",
        volgnummer=volgnummer,
        omschrijving=omschrijving,
        afschriftnummer="001",
        categorie=categorie,
        merchant_name=merchant_name,
        import_hash=uuid.uuid4().hex,
        category_id=category_id,
        is_incidental=is_incidental,
    )
    db.add(tx)
    db.flush()
    return tx


def make_category(db: Session, *, name: str = "Groceries") -> Category:
    cat = Category(name=name)
    db.add(cat)
    db.flush()
    return cat
