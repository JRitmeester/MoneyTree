import time
from pathlib import Path

from app.services.sync_import import BACKUP_RETENTION_COUNT, snapshot_sqlite_db


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


def test_snapshot_prunes_old_backups_beyond_retention(tmp_path):
    src = tmp_path / "moneytree.db"
    src.write_bytes(b"DB CONTENT")
    backup_dir = tmp_path / "backups"

    # Take BACKUP_RETENTION_COUNT + 3 snapshots, with deterministic mtime order
    paths = []
    for i in range(BACKUP_RETENTION_COUNT + 3):
        p = snapshot_sqlite_db(src, backup_dir=backup_dir)
        # Force unique mtime so prune order is deterministic across fast filesystems
        Path(p).touch()
        import os
        os.utime(p, (i, i))
        paths.append(Path(p))

    remaining = sorted(backup_dir.glob("moneytree-pre-import-*.db"))
    assert len(remaining) == BACKUP_RETENTION_COUNT
    # The 3 oldest should have been pruned
    for stale in paths[:3]:
        assert not stale.exists()
    # The newest BACKUP_RETENTION_COUNT should still exist
    for kept in paths[3:]:
        assert kept.exists()


def test_snapshot_does_not_prune_when_under_retention(tmp_path):
    src = tmp_path / "moneytree.db"
    src.write_bytes(b"DB CONTENT")
    backup_dir = tmp_path / "backups"

    # Take fewer than retention count
    for _ in range(3):
        snapshot_sqlite_db(src, backup_dir=backup_dir)
        time.sleep(0.01)

    remaining = list(backup_dir.glob("moneytree-pre-import-*.db"))
    assert len(remaining) == 3
