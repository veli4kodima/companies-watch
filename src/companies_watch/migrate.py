from pathlib import Path

import psycopg
from psycopg.rows import TupleRow

from companies_watch.config import get_settings

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"
LOCK_ID = 727001  # произвольное число для advisory lock


def apply_migrations(
    conn: psycopg.Connection[TupleRow], migrations_dir: Path
) -> list[str]:
    conn.execute(
        """
        create table if not exists schema_migrations (
            version    text primary key,
            applied_at timestamptz not null default now()
        )
        """
    )
    applied: set[str] = {
        row[0] for row in conn.execute("select version from schema_migrations")
    }

    newly_applied: list[str] = []
    for path in sorted(migrations_dir.glob("*.sql")):
        version = path.stem
        if version in applied:
            continue

        sql = path.read_text(encoding="utf-8")
        with conn.transaction():
            conn.execute(sql)
            conn.execute(
                "insert into schema_migrations (version) values (%s)",
                (version,),
            )
        print(f"applied {version}")
        newly_applied.append(version)

    return newly_applied


def main() -> None:
    settings = get_settings()
    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        conn.execute("select pg_advisory_lock(%s)", (LOCK_ID,))
        applied = apply_migrations(conn, MIGRATIONS_DIR)

    if not applied:
        print("nothing to apply")
