"""
init_db.py  –  Cross-platform database initializer.

Runs schema.sql against the configured MariaDB/MySQL server. Replaces
`mysql -u root -p < schema.sql`, which relies on shell input redirection
that PowerShell does not support the same way bash does.

Run:
    python init_db.py
"""

import os
import sys

import pymysql
from dotenv import load_dotenv

load_dotenv()

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", 3306))
DB_USER = os.getenv("DB_USER", "root")
DB_PASS = os.getenv("DB_PASS", "")

SCHEMA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")


def split_statements(sql: str) -> list[str]:
    """Strip `--` comments and split into individual statements on ';'.

    schema.sql has no stored procedures / triggers / custom DELIMITER,
    so a plain split on ';' is safe here.
    """
    statements = []
    for raw_stmt in sql.split(";"):
        lines = [ln for ln in raw_stmt.splitlines() if not ln.strip().startswith("--")]
        stmt = "\n".join(lines).strip()
        if stmt:
            statements.append(stmt)
    return statements


def main():
    if not os.path.exists(SCHEMA_FILE):
        print(f"ERROR: schema.sql not found at {SCHEMA_FILE}")
        sys.exit(1)

    with open(SCHEMA_FILE, "r", encoding="utf-8") as f:
        statements = split_statements(f.read())

    print(f"Connecting to {DB_HOST}:{DB_PORT} as {DB_USER} ...")
    conn = pymysql.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASS,
        charset="utf8mb4", autocommit=True,
    )
    try:
        with conn.cursor() as cur:
            for stmt in statements:
                first_line = stmt.splitlines()[0][:70]
                cur.execute(stmt)
                print(f"OK: {first_line}")
    finally:
        conn.close()

    print("\nDatabase initialised successfully.")
    print("Tables created: telemetry, rules, alerts (3 default rules seeded).")


if __name__ == "__main__":
    main()
