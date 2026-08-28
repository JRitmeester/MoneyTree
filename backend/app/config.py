import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR.parent / "data"
UPLOADS_DIR = BASE_DIR / "uploads"

DATABASE_URL = f"sqlite:///{DATA_DIR / 'moneytree.db'}"

DATA_DIR.mkdir(exist_ok=True)
UPLOADS_DIR.mkdir(exist_ok=True)

def load_or_create_jwt_secret(data_dir: Path, env_value: str) -> str:
    """The JWT signing secret. An explicitly set env value wins (and must be
    strong); otherwise a random secret is generated once and persisted in
    the data directory, so users never have to configure it. Regenerating
    it only logs everyone out."""
    if env_value and env_value != "change-this-secret":
        if len(env_value) < 32:
            raise RuntimeError(
                "JWT_SECRET must be a strong random value (>= 32 chars). "
                "Generate one with: openssl rand -hex 32, or unset it to "
                "let MoneyTree manage one automatically."
            )
        return env_value

    secret_file = Path(data_dir) / "jwt_secret"
    if secret_file.exists():
        stored = secret_file.read_text().strip()
        if len(stored) >= 32:
            return stored
    import secrets as _secrets

    generated = _secrets.token_urlsafe(48)
    secret_file.write_text(generated)
    try:
        secret_file.chmod(0o600)
    except OSError:
        pass
    return generated


# Auth. Username/password-hash env vars are optional: when absent, the
# first-run setup flow stores credentials in the database instead.
AUTH_USERNAME = os.getenv("AUTH_USERNAME", "admin")
AUTH_PASSWORD_HASH = os.getenv("AUTH_PASSWORD_HASH", "")
JWT_SECRET = load_or_create_jwt_secret(DATA_DIR, os.getenv("JWT_SECRET", ""))
JWT_EXPIRE_DAYS = int(os.getenv("JWT_EXPIRE_DAYS", "7"))

# WebAuthn / Passkey
RP_ID = os.getenv("RP_ID", "localhost")
RP_ORIGIN = os.getenv("RP_ORIGIN", "http://localhost:8000")
