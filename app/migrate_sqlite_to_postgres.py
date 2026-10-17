from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from sqlalchemy import text

from .database import write_session

ROOT = Path(__file__).resolve().parents[1]
TABLES = (
    "users",
    "sessions",
    "profiles",
    "behaviors",
    "orders",
    "order_events",
    "messages",
    "faqs",
    "traces",
    "model_calls",
)


def migrate(source: Path) -> dict[str, int]:
    if not source.is_file():
        raise FileNotFoundError(f"SQLite database not found: {source}")

    sqlite = sqlite3.connect(f"file:{source.resolve().as_posix()}?mode=ro", uri=True)
    sqlite.row_factory = sqlite3.Row
    try:
        source_tables = {
            row[0]
            for row in sqlite.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        missing = set(TABLES) - source_tables
        if missing:
            raise RuntimeError(f"SQLite database is missing tables: {', '.join(sorted(missing))}")

        records = {
            table: [dict(row) for row in sqlite.execute(f'SELECT * FROM "{table}"')]
            for table in TABLES
        }
    finally:
        sqlite.close()

    with write_session() as session:
        target_counts = {
            table: session.execute(text(f'SELECT COUNT(*) FROM "{table}"')).scalar_one()
            for table in TABLES
        }
        only_bootstrap_user = all(
            count == (1 if table == "users" else 0)
            for table, count in target_counts.items()
        )
        if not only_bootstrap_user:
            raise RuntimeError(
                "Target PostgreSQL tables are not empty; migration stopped to avoid merging records"
            )

        if target_counts["users"]:
            session.execute(
                text("DELETE FROM users WHERE id = 1 AND nickname = 'Demo User' AND email IS NULL")
            )
            remaining = session.execute(text("SELECT COUNT(*) FROM users")).scalar_one()
            if remaining:
                raise RuntimeError("Target contains a non-bootstrap user; migration stopped")

        for table in TABLES:
            rows = records[table]
            if not rows:
                continue
            columns = tuple(rows[0])
            column_sql = ", ".join(f'"{column}"' for column in columns)
            values_sql = ", ".join(f":{column}" for column in columns)
            statement = text(
                f'INSERT INTO "{table}" ({column_sql}) VALUES ({values_sql}) '
                "ON CONFLICT DO NOTHING"
            )
            session.execute(statement, rows)

            sequence = session.execute(
                text("SELECT pg_get_serial_sequence(:table_name, 'id')"),
                {"table_name": table},
            ).scalar_one_or_none()
            if sequence:
                maximum = session.execute(text(f'SELECT MAX(id) FROM "{table}"')).scalar_one()
                if maximum is not None:
                    session.execute(
                        text("SELECT setval(CAST(:sequence AS regclass), :value, true)"),
                        {"sequence": sequence, "value": maximum},
                    )

    return {table: len(rows) for table, rows in records.items()}


def main() -> None:
    parser = argparse.ArgumentParser(description="Copy legacy VoiceShop SQLite records to PostgreSQL")
    parser.add_argument(
        "--source",
        type=Path,
        default=ROOT / "data" / "voiceshop.db",
        help="SQLite file to read; the source is opened read-only and never modified",
    )
    args = parser.parse_args()
    copied = migrate(args.source)
    total = sum(copied.values())
    print(f"Copied {total} records from {args.source}")
    for table, count in copied.items():
        print(f"{table}: {count}")


if __name__ == "__main__":
    main()
