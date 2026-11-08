"""
migrate_add_deauth_metrics.py  –  One-time migration for existing databases.

Adds the tx_errors / clients_found / send_interval_ms columns to the
telemetry table (added to schema.sql after the DB was already created).
Safe to run more than once — skips columns that already exist.

Run:
    python migrate_add_deauth_metrics.py
"""

import pymysql

from db import get_conn

COLUMNS = [
    ("tx_errors",        "BIGINT UNSIGNED NOT NULL DEFAULT 0 AFTER deauth_pkts"),
    ("clients_found",    "INT UNSIGNED NOT NULL DEFAULT 0 AFTER tx_errors"),
    ("send_interval_ms", "INT UNSIGNED NOT NULL DEFAULT 0 AFTER clients_found"),
]


def main():
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            for name, definition in COLUMNS:
                try:
                    cur.execute(f"ALTER TABLE telemetry ADD COLUMN {name} {definition}")
                    print(f"Added column: {name}")
                except pymysql.err.OperationalError as exc:
                    if exc.args[0] == 1060:  # ER_DUP_FIELDNAME
                        print(f"Column already exists, skipping: {name}")
                    else:
                        raise
    finally:
        conn.close()

    print("\nMigration complete.")


if __name__ == "__main__":
    main()
