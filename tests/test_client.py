import pytest

from companies_watch.client import normalize_number


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("6", "00000006"),
        ("00000006", "00000006"),
        (" sc123456 ", "SC123456"),
        ("NI019468", "NI019468"),
    ],
)
def test_normalize_number_valid(raw: str, expected: str) -> None:
    assert normalize_number(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["", "   ", "../../etc", "123456789", "AB-12345", "12 34"],
)
def test_normalize_number_rejects_garbage(raw: str) -> None:
    with pytest.raises(ValueError):
        normalize_number(raw)
