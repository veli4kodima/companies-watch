import re
from datetime import date
from typing import Any

import httpx

BASE_URL = "https://api.company-information.service.gov.uk"
NUMBER_RE = re.compile(r"^[A-Z0-9]{8}$")


class CompanyNotFound(Exception):
    pass


def normalize_number(raw: str) -> str:
    number = raw.strip().upper().zfill(8)
    if not NUMBER_RE.fullmatch(number):
        raise ValueError(f"invalid company number: {raw!r}")
    return number


def make_client(api_key: str) -> httpx.Client:
    return httpx.Client(
        base_url=BASE_URL,
        auth=(api_key, ""),
        timeout=httpx.Timeout(10.0, connect=5.0),
        headers={"Accept": "application/json"},
    )


def get_company(client: httpx.Client, number: str) -> dict[str, Any]:
    response = client.get(f"/company/{number}")
    if response.status_code == 404:
        raise CompanyNotFound(number)
    response.raise_for_status()
    data: dict[str, Any] = response.json()
    return data


def search_companies(
    client: httpx.Client,
    *,
    status: str | None = None,
    sic_codes: list[str] | None = None,
    incorporated_from: date | None = None,
    incorporated_to: date | None = None,
    size: int = 100,
) -> list[str]:
    params: dict[str, str | int | list[str]] = {"size": size}
    if status:
        params["company_status"] = status
    if sic_codes:
        params["sic_codes"] = sic_codes
    if incorporated_from:
        params["incorporated_from"] = incorporated_from.isoformat()
    if incorporated_to:
        params["incorporated_to"] = incorporated_to.isoformat()

    response = client.get("/advanced-search/companies", params=params)
    if response.status_code == 404:
        return []
    response.raise_for_status()
    items: list[dict[str, Any]] = response.json().get("items", [])
    return [item["company_number"] for item in items]
