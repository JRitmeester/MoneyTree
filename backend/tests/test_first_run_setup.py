"""Tests for the first-run setup flow: browser-based account creation when
no credentials are configured, and JWT-secret auto-generation."""
import pytest
from sqlalchemy.orm import Session

from app.config import load_or_create_jwt_secret
from app.models import AppSetting, PasskeyCredential
from app.routers import auth as auth_router


class TestJwtSecret:
    def test_explicit_env_value_wins(self, tmp_path):
        secret = "x" * 40
        assert load_or_create_jwt_secret(tmp_path, secret) == secret

    def test_short_env_value_rejected(self, tmp_path):
        with pytest.raises(RuntimeError):
            load_or_create_jwt_secret(tmp_path, "short")

    def test_placeholder_treated_as_unset(self, tmp_path):
        generated = load_or_create_jwt_secret(tmp_path, "change-this-secret")
        assert generated != "change-this-secret"
        assert len(generated) >= 32

    def test_generated_secret_persists(self, tmp_path):
        first = load_or_create_jwt_secret(tmp_path, "")
        second = load_or_create_jwt_secret(tmp_path, "")
        assert first == second
        assert len(first) >= 32
        assert (tmp_path / "jwt_secret").exists()


class TestSetupFlow:
    def test_needs_setup_when_nothing_configured(self, client):
        body = client.get("/api/auth/setup-status").json()
        assert body["needs_setup"] is True

    def test_env_hash_disables_setup(self, client, monkeypatch):
        monkeypatch.setattr(auth_router.config, "AUTH_PASSWORD_HASH", "$2b$fake")
        body = client.get("/api/auth/setup-status").json()
        assert body["needs_setup"] is False

    def test_existing_passkey_disables_setup(self, client, db: Session):
        db.add(PasskeyCredential(
            credential_id=b"abc", public_key=b"def", sign_count=0, name="key",
        ))
        db.commit()
        body = client.get("/api/auth/setup-status").json()
        assert body["needs_setup"] is False

    def test_setup_creates_account_and_logs_in(self, client, db: Session):
        resp = client.post(
            "/api/auth/setup",
            json={"username": "tester", "password": "hunter2hunter2"},
        )
        assert resp.status_code == 200
        assert "auth_token" in resp.cookies

        assert db.get(AppSetting, "auth_username").value == "tester"
        assert db.get(AppSetting, "auth_password_hash").value.startswith("$2b$")

        assert client.get("/api/auth/setup-status").json()["needs_setup"] is False

        login = client.post(
            "/api/auth/login",
            json={"username": "tester", "password": "hunter2hunter2"},
        )
        assert login.status_code == 200

        bad = client.post(
            "/api/auth/login",
            json={"username": "tester", "password": "wrong-password"},
        )
        assert bad.status_code == 401

    def test_setup_rejected_once_configured(self, client):
        assert client.post(
            "/api/auth/setup",
            json={"username": "tester", "password": "hunter2hunter2"},
        ).status_code == 200
        resp = client.post(
            "/api/auth/setup",
            json={"username": "intruder", "password": "hunter2hunter2"},
        )
        assert resp.status_code == 409

    def test_setup_rejects_weak_password(self, client):
        resp = client.post(
            "/api/auth/setup", json={"username": "tester", "password": "short"}
        )
        assert resp.status_code == 422

    def test_db_credentials_beat_env(self, client, db: Session, monkeypatch):
        client.post(
            "/api/auth/setup",
            json={"username": "tester", "password": "hunter2hunter2"},
        )
        monkeypatch.setattr(auth_router.config, "AUTH_PASSWORD_HASH", "$2b$fake")
        monkeypatch.setattr(auth_router.config, "AUTH_USERNAME", "envuser")
        login = client.post(
            "/api/auth/login",
            json={"username": "tester", "password": "hunter2hunter2"},
        )
        assert login.status_code == 200

    def test_delete_everything_preserves_account(self, client, db: Session):
        client.post(
            "/api/auth/setup",
            json={"username": "tester", "password": "hunter2hunter2"},
        )
        assert client.delete("/api/settings/everything").status_code == 200
        assert db.get(AppSetting, "auth_password_hash") is not None
        assert client.get("/api/auth/setup-status").json()["needs_setup"] is False
