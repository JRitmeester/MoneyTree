from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR.parent / "data"
UPLOADS_DIR = BASE_DIR / "uploads"

DATABASE_URL = f"sqlite:///{DATA_DIR / 'moneytree.db'}"

DATA_DIR.mkdir(exist_ok=True)
UPLOADS_DIR.mkdir(exist_ok=True)
