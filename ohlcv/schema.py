from __future__ import annotations
from pathlib import Path
from datetime import datetime
from lightql import connect

META_SQL = """
CREATE TABLE IF NOT EXISTS ohlcv_migrations (
  version TEXT PRIMARY KEY,
  applied_at TEXT NOT NULL
);
"""


def ensure_schema(dsn: str, sql_root: Path) -> None:
    conn = connect(dsn)
    c = conn.conn  # underlying sqlite3.Connection (autocommit None)
    c.execute("PRAGMA journal_mode=WAL;")
    c.execute(META_SQL)
    c.commit()

    mig_dir = sql_root / "migrations"
    files = sorted([p for p in mig_dir.glob("*.sql")])
    for f in files:
        version = f.stem.split("_")[0]  # e.g., 0001
        cur = c.execute("SELECT 1 FROM ohlcv_migrations WHERE version=?", (version,)).fetchone()
        if cur:
            continue
        with open(f, "r", encoding="utf-8") as fh:
            sql = fh.read()
        c.executescript(sql)
        c.execute(
            "INSERT INTO ohlcv_migrations(version, applied_at) VALUES(?, ?)",
            (version, datetime.utcnow().isoformat(timespec="seconds") + "Z"),
        )
        c.commit()
