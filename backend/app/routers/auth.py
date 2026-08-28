import json
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import webauthn
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, model_validator
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session
from webauthn.helpers import base64url_to_bytes
from webauthn.helpers.structs import (
    AuthenticationCredential,
    AuthenticatorAssertionResponse,
    AuthenticatorAttestationResponse,
    PublicKeyCredentialDescriptor,
    RegistrationCredential,
)

from ..auth import cleanup_expired_revocations, create_token, require_auth, revoke_token, verify_token
from .. import config
from ..config import JWT_EXPIRE_DAYS, RP_ID, RP_ORIGIN
from ..database import get_db
from ..models import AppSetting, PasskeyCredential, WebAuthnChallenge

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])
limiter = Limiter(key_func=get_remote_address)

_CHALLENGE_TTL = 60

_SECURE_COOKIE = RP_ORIGIN.startswith("https://")


# --- Challenge storage (database-backed) ---

def _store_challenge(db: Session, challenge: bytes) -> str:
    token = os.urandom(16).hex()

    # Prune expired challenges
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=_CHALLENGE_TTL)
    db.query(WebAuthnChallenge).filter(WebAuthnChallenge.created_at < cutoff).delete()

    entry = WebAuthnChallenge(
        token=token,
        challenge=challenge,
        created_at=datetime.now(timezone.utc),
    )
    db.add(entry)
    db.commit()
    return token


def _pop_challenge(db: Session, token: str) -> bytes | None:
    entry = db.query(WebAuthnChallenge).filter(WebAuthnChallenge.token == token).first()
    if not entry:
        return None

    db.delete(entry)
    db.commit()

    cutoff = datetime.now(timezone.utc) - timedelta(seconds=_CHALLENGE_TTL)
    if entry.created_at < cutoff:
        return None

    return entry.challenge


def _set_auth_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key="auth_token",
        value=token,
        httponly=True,
        samesite="strict",
        secure=_SECURE_COOKIE,
        path="/",
        max_age=JWT_EXPIRE_DAYS * 24 * 3600,
    )


# --- Password login and first-run setup ---

def _resolve_credentials(db: Session) -> tuple[str, str]:
    """(username, bcrypt hash) to check logins against: account created via
    the first-run setup flow (stored in app_settings) wins; env-configured
    credentials are the fallback for deployments like the NAS."""
    stored_hash = db.get(AppSetting, "auth_password_hash")
    if stored_hash is not None:
        stored_user = db.get(AppSetting, "auth_username")
        username = stored_user.value if stored_user is not None else "admin"
        return username, stored_hash.value
    return config.AUTH_USERNAME, config.AUTH_PASSWORD_HASH


def _needs_setup(db: Session) -> bool:
    """First-run setup is open only while NO way to authenticate exists:
    no env-configured hash, no stored account, and no registered passkey."""
    if config.AUTH_PASSWORD_HASH:
        return False
    if db.get(AppSetting, "auth_password_hash") is not None:
        return False
    if db.query(PasskeyCredential).first() is not None:
        return False
    return True


class LoginRequest(BaseModel):
    username: str
    password: str


class SetupRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=8, max_length=200)

    @model_validator(mode="after")
    def _strip(self):
        stripped = self.username.strip()
        if not stripped:
            raise ValueError("Username must not be blank")
        self.username = stripped
        return self


@router.get("/setup-status")
def setup_status(db: Session = Depends(get_db)):
    return {"needs_setup": _needs_setup(db)}


@router.post("/setup")
@limiter.limit("5/minute")
def setup(request: Request, body: SetupRequest, response: Response, db: Session = Depends(get_db)):
    """Create the account on first run and log the new user straight in.
    Rejected as soon as any way to authenticate exists."""
    if not _needs_setup(db):
        raise HTTPException(status_code=409, detail="MoneyTree is already set up")

    password_hash = bcrypt.hashpw(body.password.encode(), bcrypt.gensalt()).decode()
    db.add(AppSetting(key="auth_username", value=body.username))
    db.add(AppSetting(key="auth_password_hash", value=password_hash))
    db.commit()

    token = create_token(body.username)
    _set_auth_cookie(response, token)
    return {"ok": True}


@router.post("/login")
@limiter.limit("5/minute")
def login(request: Request, body: LoginRequest, response: Response, db: Session = Depends(get_db)):
    expected_username, expected_hash = _resolve_credentials(db)
    username_ok = secrets.compare_digest(body.username, expected_username)
    password_ok = bool(expected_hash) and bcrypt.checkpw(
        body.password.encode(), expected_hash.encode()
    )
    if not (username_ok and password_ok):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_token(body.username)
    _set_auth_cookie(response, token)
    return {"ok": True}


@router.post("/logout")
def logout(
    response: Response,
    auth_token: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    if auth_token:
        revoke_token(auth_token, db)
        cleanup_expired_revocations(db)
    response.delete_cookie(
        "auth_token", httponly=True, samesite="strict", secure=_SECURE_COOKIE, path="/",
    )
    return {"ok": True}


@router.get("/me")
@limiter.limit("30/minute")
def me(
    request: Request,
    auth_token: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    if not auth_token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    username = verify_token(auth_token, db=db)
    if not username:
        raise HTTPException(status_code=401, detail="Invalid token")
    return {"username": username}


# --- Passkey registration (requires existing session) ---

@router.get("/passkey/register/begin")
@limiter.limit("10/minute")
def passkey_register_begin(
    request: Request,
    _username: str = Depends(require_auth),
    db: Session = Depends(get_db),
):
    existing = db.query(PasskeyCredential).all()
    exclude_credentials = [
        PublicKeyCredentialDescriptor(id=cred.credential_id)
        for cred in existing
    ]

    options = webauthn.generate_registration_options(
        rp_id=RP_ID,
        rp_name="MoneyTree",
        user_id=b"moneytree-admin",
        user_name=AUTH_USERNAME,
        user_display_name="MoneyTree Admin",
        exclude_credentials=exclude_credentials,
    )
    challenge_token = _store_challenge(db, options.challenge)
    options_json = json.loads(webauthn.options_to_json(options))
    options_json["challenge_token"] = challenge_token
    return JSONResponse(content=options_json)


class RegisterCompleteRequest(BaseModel):
    credential: dict
    challenge_token: str
    name: str = "My Passkey"


@router.post("/passkey/register/complete")
@limiter.limit("10/minute")
def passkey_register_complete(
    request: Request,
    body: RegisterCompleteRequest,
    _username: str = Depends(require_auth),
    db: Session = Depends(get_db),
):
    challenge = _pop_challenge(db, body.challenge_token)
    if challenge is None:
        raise HTTPException(status_code=400, detail="Challenge expired or invalid")

    try:
        cred_data = body.credential
        credential = RegistrationCredential(
            id=cred_data["id"],
            raw_id=base64url_to_bytes(cred_data["rawId"]),
            response=AuthenticatorAttestationResponse(
                client_data_json=base64url_to_bytes(cred_data["response"]["clientDataJSON"]),
                attestation_object=base64url_to_bytes(cred_data["response"]["attestationObject"]),
            ),
        )
        verification = webauthn.verify_registration_response(
            credential=credential,
            expected_challenge=challenge,
            expected_rp_id=RP_ID,
            expected_origin=RP_ORIGIN,
        )
    except Exception:
        logger.exception("Passkey registration failed")
        raise HTTPException(status_code=400, detail="Registration failed")

    new_cred = PasskeyCredential(
        credential_id=verification.credential_id,
        public_key=verification.credential_public_key,
        sign_count=verification.sign_count,
        name=body.name,
        created_at=datetime.now(timezone.utc),
    )
    db.add(new_cred)
    db.commit()
    return {"ok": True, "name": body.name}


# --- Passkey authentication ---

class PasskeyAuthCompleteRequest(BaseModel):
    id: str
    rawId: str
    challenge_token: str
    response: dict
    type: str = "public-key"
    authenticatorAttachment: str | None = None
    clientExtensionResults: dict | None = None


@router.get("/passkey/auth/begin")
@limiter.limit("10/minute")
def passkey_auth_begin(request: Request, db: Session = Depends(get_db)):
    credentials = db.query(PasskeyCredential).all()
    allow_credentials = [
        PublicKeyCredentialDescriptor(id=cred.credential_id)
        for cred in credentials
    ]
    options = webauthn.generate_authentication_options(
        rp_id=RP_ID,
        allow_credentials=allow_credentials,
    )
    challenge_token = _store_challenge(db, options.challenge)
    options_json = json.loads(webauthn.options_to_json(options))
    options_json["challenge_token"] = challenge_token
    return JSONResponse(content=options_json)


@router.post("/passkey/auth/complete")
@limiter.limit("10/minute")
def passkey_auth_complete(
    request: Request,
    body: PasskeyAuthCompleteRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    challenge = _pop_challenge(db, body.challenge_token)
    if challenge is None:
        raise HTTPException(status_code=400, detail="Challenge expired or invalid")

    try:
        credential = AuthenticationCredential(
            id=body.id,
            raw_id=base64url_to_bytes(body.rawId),
            response=AuthenticatorAssertionResponse(
                client_data_json=base64url_to_bytes(body.response["clientDataJSON"]),
                authenticator_data=base64url_to_bytes(body.response["authenticatorData"]),
                signature=base64url_to_bytes(body.response["signature"]),
                user_handle=(
                    base64url_to_bytes(body.response["userHandle"])
                    if body.response.get("userHandle")
                    else None
                ),
            ),
        )
    except Exception:
        logger.exception("Invalid passkey credential")
        raise HTTPException(status_code=400, detail="Invalid credential")

    stored = db.query(PasskeyCredential).filter(
        PasskeyCredential.credential_id == credential.raw_id
    ).first()
    if not stored:
        raise HTTPException(status_code=401, detail="Authentication failed")

    try:
        verification = webauthn.verify_authentication_response(
            credential=credential,
            expected_challenge=challenge,
            expected_rp_id=RP_ID,
            expected_origin=RP_ORIGIN,
            credential_public_key=stored.public_key,
            credential_current_sign_count=stored.sign_count,
        )
    except Exception:
        logger.exception("Passkey authentication failed")
        raise HTTPException(status_code=401, detail="Authentication failed")

    stored.sign_count = verification.new_sign_count
    db.commit()

    token = create_token(AUTH_USERNAME)
    _set_auth_cookie(response, token)
    return {"ok": True}
