from typing import Any

TRACKED_FIELDS = (
    "company_name",
    "company_status",
    "registered_office_address",
    "sic_codes",
    "date_of_cessation",
)


def diff_fields(old: dict[str, Any], new: dict[str, Any]) -> list[tuple[str, Any, Any]]:
    return [
        (field, old.get(field), new.get(field))
        for field in TRACKED_FIELDS
        if old.get(field) != new.get(field)
    ]
