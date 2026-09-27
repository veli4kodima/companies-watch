from companies_watch.changes import diff_fields

BASE = {
    "company_number": "00000006",
    "company_name": "ACME LTD",
    "company_status": "active",
    "registered_office_address": {"postal_code": "EC1A 1BB", "locality": "London"},
    "sic_codes": ["62012"],
    "etag": "e1",
}


def test_no_changes() -> None:
    assert diff_fields(BASE, dict(BASE)) == []


def test_tracked_field_change() -> None:
    new = {**BASE, "company_status": "dissolved"}
    assert diff_fields(BASE, new) == [("company_status", "active", "dissolved")]


def test_untracked_field_is_ignored() -> None:
    new = {**BASE, "etag": "e2", "links": {"self": "/company/00000006"}}
    assert diff_fields(BASE, new) == []


def test_field_appears() -> None:
    new = {**BASE, "date_of_cessation": "2026-09-01"}
    assert diff_fields(BASE, new) == [("date_of_cessation", None, "2026-09-01")]


def test_nested_change_is_detected() -> None:
    address = {**BASE["registered_office_address"], "postal_code": "SW1A 1AA"}
    new = {**BASE, "registered_office_address": address}
    [(field, old, value)] = diff_fields(BASE, new)
    assert field == "registered_office_address"
    assert old["postal_code"] == "EC1A 1BB"
    assert value["postal_code"] == "SW1A 1AA"


def test_order_follows_tracked_fields() -> None:
    new = {**BASE, "sic_codes": ["62020"], "company_name": "ACME 2 LTD"}
    assert [f for f, _, _ in diff_fields(BASE, new)] == ["company_name", "sic_codes"]
