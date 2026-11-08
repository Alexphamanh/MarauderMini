"""
db.py  –  Shared database connection helper.
All modules import `get_conn()` from here.
"""
import os
import pymysql
import pymysql.cursors
from dotenv import load_dotenv

load_dotenv()

DB_CFG = {
    "host":   os.getenv("DB_HOST", "localhost"),
    "port":   int(os.getenv("DB_PORT", 3306)),
    "db":     os.getenv("DB_NAME", "marauder_db"),
    "user":   os.getenv("DB_USER", "root"),
    "passwd": os.getenv("DB_PASS", ""),
    "charset": "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor,
    "autocommit": True,
}


def get_conn():
    """Return a new PyMySQL connection. Caller is responsible for closing."""
    return pymysql.connect(**DB_CFG)
