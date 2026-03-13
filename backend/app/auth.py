import uuid
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Cookie, Depends, HTTPException
from sqlalchemy.orm import Session

from .config import JWT_EXPIRE_DAYS, JWT_SECRET
from .database import get_db


def create_token(username: str) -> str:
    payload = {
        "sub": username,
        "jti": uuid.uuid4().hex,
        "exp": datetime.now(timezone.utc) + timedelta(days=JWT_EXPIRE_DAYS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def verify_token(token: str, db: Session | None = None) -> str | None:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None

    jti = payload.get("jti")
    if jti and db is not None:
        from .models import RevokedToken

        if db.query(RevokedToken).filter(RevokedToken.jti == jti).first():
            return None

    return payload.get("sub")


def revoke_token(token: str, db: Session) -> None:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        return

    jti = payload.get("jti")
    exp = payload.get("exp")
    if not jti or not exp:
        return

    from .models import RevokedToken

    if db.query(RevokedToken).filter(RevokedToken.jti == jti).first():
        return

    revoked = RevokedToken(
        jti=jti,
        expires_at=datetime.fromtimestamp(exp, tz=timezone.utc),
    )
    db.add(revoked)
    db.commit()


def cleanup_expired_revocations(db: Session) -> None:
    from .models import RevokedToken

    now = datetime.now(timezone.utc)
    db.query(RevokedToken).filter(RevokedToken.expires_at < now).delete()
    db.commit()


def require_auth(
    auth_token: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
) -> str:
    if not auth_token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    username = verify_token(auth_token, db=db)
    if not username:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return username
