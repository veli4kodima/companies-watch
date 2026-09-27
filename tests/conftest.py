import os
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import TupleRow

ADMIN_URL = os.environ.get(
    "TEST_ADMIN_DATABASE_URL", "postgresql://app:app@127.0.0.1:5432/postgres"
)
TEST_DB = "companies_watch_test"
MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations"
TRUNCATE_SQL = (
    "truncate company_changes, companies, watchlist, refresh_log restart identity"
)


@pytest.fixture(scope="session")
def test_db_url() -> str:
    try:
        admin = psycopg.connect(ADMIN_URL, autocommit=True, connect_timeout=3)
    except psycopg.OperationalError as exc:
        pytest.skip(f"postgres not available: {exc}")

    with admin:
        name = sql.Identifier(TEST_DB)
        admin.execute(sql.SQL("drop database if exists {} with (force)").format(name))
        admin.execute(sql.SQL("create database {}").format(name))

    url = make_conninfo(ADMIN_URL, dbname=TEST_DB)
    with psycopg.connect(url, autocommit=True) as conn:
        for path in sorted(MIGRATIONS.glob("*.sql")):
            conn.execute(path.read_text(encoding="utf-8"))
    return url


@pytest.fixture
def conn(test_db_url: str) -> Iterator[psycopg.Connection[TupleRow]]:
    with psycopg.connect(test_db_url, autocommit=True) as c:
        c.execute(TRUNCATE_SQL)
        yield c
