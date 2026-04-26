import json
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import ValidationError
from sqlalchemy.orm import Session

from ..auth import require_auth
from ..config import DATA_DIR
from ..database import get_db
from ..services.sync_export import build_export
from ..services.sync_import import commit_import, preview_import, snapshot_sqlite_db
from ..sync_schemas import ExportFile, ImportResult

router = APIRouter(prefix="/api/sync", tags=["sync"], dependencies=[Depends(require_auth)])


@router.get("/export", response_model=ExportFile)
def export_sync(
    since: Optional[date] = Query(None, description="Only include transactions with created_at >= since"),
    db: Session = Depends(get_db),
):
    return build_export(db, since=since)


@router.post("/import", response_model=ImportResult)
async def import_sync(
    file: UploadFile = File(...),
    dry_run: bool = True,
    update_duplicates: bool = False,
    db: Session = Depends(get_db),
):
    raw = await file.read()
    try:
        data = json.loads(raw)
        export = ExportFile.model_validate(data)
    except (ValidationError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail=f"Invalid export file: {exc}")

    if dry_run:
        preview = preview_import(db, export)
        return ImportResult(preview=preview, committed=False, backup_path=None)

    backup_path = snapshot_sqlite_db(
        db_path=DATA_DIR / "moneytree.db",
        backup_dir=DATA_DIR / "backups",
    )
    try:
        preview = commit_import(db, export, update_duplicates=update_duplicates)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc))
    return ImportResult(preview=preview, committed=True, backup_path=backup_path)
