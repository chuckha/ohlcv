from __future__ import annotations
from pathlib import Path
from lightql.migrations import apply_migrations

def ensure_schema(dsn: str, sql_root: Path) -> None:
    # Use lightql's canonical `schema_migrations` table
    apply_migrations(dsn=dsn, sql_dir=str(sql_root))
