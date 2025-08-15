from __future__ import annotations
from pathlib import Path
import tempfile, shutil
from importlib import resources

_SQL_CACHE_TAG = "sql"


def unpack_sql_package() -> Path:
    """Copy `ohlcv/sql/**` package resources to a temp dir and return its path.

    We do this because lightql loads queries/migrations from filesystem paths.
    The temp dir is process-scoped; callers don't pass sql_dir anymore.
    """
    tmp = Path(tempfile.mkdtemp(prefix="ohlcv_sql_"))
    pkg = resources.files("ohlcv") / "sql"
    # Recursively copy Traversable -> disk
    for entry in pkg.rglob("*"):
        rel = entry.relative_to(pkg)
        dst = tmp / rel
        if entry.is_dir():
            dst.mkdir(parents=True, exist_ok=True)
        else:
            with resources.as_file(entry) as src_path:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src_path, dst)
    return tmp
