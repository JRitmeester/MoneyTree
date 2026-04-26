from datetime import date, datetime, timezone
from app.sync_schemas import ExportFile, ExportCategory, ExportTransaction
import pytest
from pydantic import ValidationError


def test_export_file_serializes_round_trip():
    payload = {
        "format_version": 1,
        "exported_at": datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc),
        "since": date(2026, 4, 1),
        "categories": [
            {"name": "Groceries", "parent_name": None, "is_fixed": False, "category_type": "expense"}
        ],
        "category_mappings": [],
        "budgets": [],
        "budget_lines": [],
        "budget_templates": [],
        "transactions": [],
        "transaction_offsets": [],
    }
    parsed = ExportFile.model_validate(payload)
    dumped = parsed.model_dump(mode="json")
    reparsed = ExportFile.model_validate(dumped)
    assert reparsed.categories[0].name == "Groceries"
    assert reparsed.format_version == 1


def test_export_file_rejects_wrong_format_version():
    with pytest.raises(ValidationError):
        ExportFile.model_validate({
            "format_version": 999, "exported_at": datetime.now(timezone.utc), "since": None,
            "categories": [], "category_mappings": [], "budgets": [], "budget_lines": [],
            "budget_templates": [], "transactions": [], "transaction_offsets": [],
        })
