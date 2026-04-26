from pathlib import Path

from app.services.sync_import import snapshot_sqlite_db


def test_snapshot_creates_timestamped_copy(tmp_path):
    src = tmp_path / "moneytree.db"
    src.write_bytes(b"FAKE SQLITE BYTES")

    backup_path = snapshot_sqlite_db(src, backup_dir=tmp_path / "backups")

    assert Path(backup_path).exists()
    assert Path(backup_path).read_bytes() == b"FAKE SQLITE BYTES"
    assert "moneytree" in Path(backup_path).name
    assert Path(backup_path).suffix == ".db"


def test_snapshot_returns_none_when_source_missing(tmp_path):
    result = snapshot_sqlite_db(tmp_path / "missing.db", backup_dir=tmp_path / "backups")
    assert result is None
