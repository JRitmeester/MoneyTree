from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..auth import require_auth
from ..database import get_db
from ..services.sync_export import build_export
from ..sync_schemas import ExportFile

router = APIRouter(prefix="/api/sync", tags=["sync"], dependencies=[Depends(require_auth)])


@router.get("/export", response_model=ExportFile)
def export_sync(
    since: Optional[date] = Query(None, description="Only include transactions with created_at >= since"),
    db: Session = Depends(get_db),
):
    return build_export(db, since=since)
