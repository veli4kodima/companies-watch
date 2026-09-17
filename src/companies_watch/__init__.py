import psycopg

from companies_watch.client import get_company, make_client, normalize_number
from companies_watch.config import get_settings
from companies_watch.store import upsert_company


def main() -> None:
    settings = get_settings()

    with make_client(settings.ch_api_key.get_secret_value()) as client:
        company = get_company(client, normalize_number("6"))

    with psycopg.connect(
        settings.database_url, autocommit=True, connect_timeout=5
    ) as conn, conn.transaction():
        upsert_company(conn, company)

    print(f"saved {company['company_number']} {company['company_name']}")

