import re
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
