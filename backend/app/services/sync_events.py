"""Helpers to record append-only sync events.

Routers call `record_event(...)` before performing renames/deletes that
the additive sync merge cannot otherwise reconstruct from natural keys.
Events are flushed in the same DB transaction as the mutation itself.
"""
import json
import uuid
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from ..models import SyncEvent


# Known event types — keep in sync with sync_import._apply_event.
EVENT_CATEGORY_RENAME = "category.rename"
EVENT_CATEGORY_DELETE = "category.delete"
EVENT_CATEGORY_UPDATE = "category.update"
EVENT_CATEGORY_MAPPING_DELETE = "category_mapping.delete"
EVENT_BUDGET_DELETE = "budget.delete"


def _serialize(value: Any) -> Any:
    if isinstance(value, date):
        return value.isoformat()
    return value


def record_event(db: Session, event_type: str, payload: dict[str, Any]) -> SyncEvent:
    """Append a sync event. Caller is responsible for the surrounding commit."""
    event = SyncEvent(
        event_id=str(uuid.uuid4()),
        event_type=event_type,
        payload_json=json.dumps({k: _serialize(v) for k, v in payload.items()}),
    )
    db.add(event)
    return event
