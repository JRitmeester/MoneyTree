import json
import logging
import os
import secrets
import time
from datetime import datetime, timezone

import bcrypt
import webauthn
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel
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

from ..auth import create_token, verify_token
from ..config import AUTH_PASSWORD_HASH, AUTH_USERNAME, JWT_EXPIRE_DAYS, RP_ID, RP_ORIGIN
from ..database import get_db
from ..models import PasskeyCredential

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])
limiter = Limiter(key_func=get_remote_address)

# Challenge storage — keyed by random token with 60s TTL
_challenges: dict[str, tuple[bytes, float]] = {}
_CHALLENGE_TTL = 60

_SECURE_COOKIE = RP_ORIGIN.startswith("https://")


def _store_challenge(challenge: bytes) -> str:
    token = os.urandom(16).hex()
    now = time.time()
    expired = [k for k, (_, ts) in _challenges.items() if now - ts > _CHALLENGE_TTL]
    for k in expired:
        del _challenges[k]
    _challenges[token] = (challenge, now)
    return token


def _pop_challenge(token: str) -> bytes | None:
    entry = _challenges.pop(token, None)
    if not entry:
        return None
    challenge, ts = entry
    return challenge if time.time() - ts <= _CHALLENGE_TTL else None


def _set_auth_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key="auth_token",
        value=token,
        httponly=True,
        samesite="strict",
        secure=_SECURE_COOKIE,
        max_age=JWT_EXPIRE_DAYS * 24 * 3600,
    )


# --- Password login ---

class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/login")
@limiter.limit("5/minute")
def login(request: Request, body: LoginRequest, response: Response):
    username_ok = secrets.compare_digest(body.username, AUTH_USERNAME)
    password_ok = bool(AUTH_PASSWORD_HASH) and bcrypt.checkpw(
        body.password.encode(), AUTH_PASSWORD_HASH.encode()
    )
    if not (username_ok and password_ok):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_token(body.username)
    _set_auth_cookie(response, token)
    return {"ok": True}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(
        "auth_token", httponly=True, samesite="strict", secure=_SECURE_COOKIE,
    )
    return {"ok": True}


@router.get("/me")
def me(auth_token: str | None = Cookie(default=None)):
    if not auth_token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    username = verify_token(auth_token)
    if not username:
        raise HTTPException(status_code=401, detail="Invalid token")
    return {"username": username}


# --- Passkey registration (requires existing session) ---

@router.get("/passkey/register/begin")
def passkey_register_begin(
    auth_token: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    if not auth_token or not verify_token(auth_token):
        raise HTTPException(status_code=401, detail="Not authenticated")

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
    challenge_token = _store_challenge(options.challenge)
    options_json = json.loads(webauthn.options_to_json(options))
    options_json["challenge_token"] = challenge_token
    return JSONResponse(content=options_json)


class RegisterCompleteRequest(BaseModel):
    credential: dict
    challenge_token: str
    name: str = "My Passkey"


@router.post("/passkey/register/complete")
def passkey_register_complete(
    body: RegisterCompleteRequest,
    auth_token: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    if not auth_token or not verify_token(auth_token):
        raise HTTPException(status_code=401, detail="Not authenticated")

    challenge = _pop_challenge(body.challenge_token)
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
    except Exception as exc:
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

@router.get("/passkey/auth/begin")
def passkey_auth_begin(db: Session = Depends(get_db)):
    credentials = db.query(PasskeyCredential).all()
    allow_credentials = [
        PublicKeyCredentialDescriptor(id=cred.credential_id)
        for cred in credentials
    ]
    options = webauthn.generate_authentication_options(
        rp_id=RP_ID,
        allow_credentials=allow_credentials,
    )
    challenge_token = _store_challenge(options.challenge)
    options_json = json.loads(webauthn.options_to_json(options))
    options_json["challenge_token"] = challenge_token
    return JSONResponse(content=options_json)


@router.post("/passkey/auth/complete")
async def passkey_auth_complete(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    body = await request.json()

    challenge_token = body.pop("challenge_token", None)
    if not challenge_token:
        raise HTTPException(status_code=400, detail="Missing challenge_token")

    challenge = _pop_challenge(challenge_token)
    if challenge is None:
        raise HTTPException(status_code=400, detail="Challenge expired or invalid")

    try:
        credential = AuthenticationCredential(
            id=body["id"],
            raw_id=base64url_to_bytes(body["rawId"]),
            response=AuthenticatorAssertionResponse(
                client_data_json=base64url_to_bytes(body["response"]["clientDataJSON"]),
                authenticator_data=base64url_to_bytes(body["response"]["authenticatorData"]),
                signature=base64url_to_bytes(body["response"]["signature"]),
                user_handle=(
                    base64url_to_bytes(body["response"]["userHandle"])
                    if body["response"].get("userHandle")
                    else None
                ),
            ),
        )
    except Exception as exc:
        logger.exception("Invalid passkey credential")
        raise HTTPException(status_code=400, detail="Invalid credential")

    stored = db.query(PasskeyCredential).filter(
        PasskeyCredential.credential_id == credential.raw_id
    ).first()
    if not stored:
        raise HTTPException(status_code=401, detail="Unknown credential")

    try:
        verification = webauthn.verify_authentication_response(
            credential=credential,
            expected_challenge=challenge,
            expected_rp_id=RP_ID,
            expected_origin=RP_ORIGIN,
            credential_public_key=stored.public_key,
            credential_current_sign_count=stored.sign_count,
        )
    except Exception as exc:
        logger.exception("Passkey authentication failed")
        raise HTTPException(status_code=401, detail="Authentication failed")

    stored.sign_count = verification.new_sign_count
    db.commit()

    token = create_token(AUTH_USERNAME)
    _set_auth_cookie(response, token)
    return {"ok": True}
