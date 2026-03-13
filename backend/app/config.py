import os
import warnings
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR.parent / "data"
UPLOADS_DIR = BASE_DIR / "uploads"

DATABASE_URL = f"sqlite:///{DATA_DIR / 'moneytree.db'}"

DATA_DIR.mkdir(exist_ok=True)
UPLOADS_DIR.mkdir(exist_ok=True)

# Auth
AUTH_USERNAME = os.getenv("AUTH_USERNAME", "admin")
AUTH_PASSWORD_HASH = os.getenv("AUTH_PASSWORD_HASH", "")
JWT_SECRET = os.getenv("JWT_SECRET", "change-this-secret")
JWT_EXPIRE_DAYS = int(os.getenv("JWT_EXPIRE_DAYS", "7"))

# WebAuthn / Passkey
RP_ID = os.getenv("RP_ID", "localhost")
RP_ORIGIN = os.getenv("RP_ORIGIN", "http://localhost:8080")


# Startup validation
def _validate_config() -> None:
    if JWT_SECRET == "change-this-secret" or len(JWT_SECRET) < 32:
        raise RuntimeError(
            "JWT_SECRET must be set to a strong random value (>= 32 chars). "
            "Generate one with: openssl rand -hex 32"
        )
    if not AUTH_PASSWORD_HASH:
        warnings.warn(
            "AUTH_PASSWORD_HASH is empty — password login is disabled",
            stacklevel=2,
        )


_validate_config()
