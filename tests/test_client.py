import httpx
import pytest

from companies_watch.client import (
    BASE_URL,
    BadResponse,
    CompanyNotFound,
    get_company,
    normalize_number,
)


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


def mock_client(status: int, body: str) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text=body)

    return httpx.Client(base_url=BASE_URL, transport=httpx.MockTransport(handler))


def test_get_company_ok() -> None:
    body = '{"company_number": "00000006", "company_name": "ACME LTD"}'
    with mock_client(200, body) as client:
        assert get_company(client, "00000006")["company_name"] == "ACME LTD"


def test_get_company_404() -> None:
    with mock_client(404, "{}") as client, pytest.raises(CompanyNotFound):
        get_company(client, "00000006")


@pytest.mark.parametrize(
    "body",
    [
        "<html>maintenance</html>",
        "[]",
        '{"company_number": "99999999", "company_name": "OTHER LTD"}',
        '{"company_number": "00000006"}',
        '{"company_number": "00000006", "company_name": null}',
    ],
    ids=["not-json", "not-object", "other-company", "no-name", "null-name"],
)
def test_get_company_bad_response(body: str) -> None:
    with mock_client(200, body) as client, pytest.raises(BadResponse):
        get_company(client, "00000006")
