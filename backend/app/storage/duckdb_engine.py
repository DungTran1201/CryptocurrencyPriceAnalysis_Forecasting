"""Resource-bounded DuckDB analytical query engine over Parquet datasets."""

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, List, Dict, Any, Optional
import duckdb

from backend.app.core.config import settings


@contextmanager
def open_bounded_duckdb() -> Iterator[duckdb.DuckDBPyConnection]:
    """Open an ephemeral in-memory DuckDB connection constrained by profile budgets."""
    conn = duckdb.connect(database=":memory:")
    try:
        conn.execute(f"SET memory_limit='{settings.resources.duckdb_memory_limit}';")
        conn.execute(f"SET threads={int(settings.resources.duckdb_threads)};")
        yield conn
    finally:
        conn.close()


def query_parquet_glob(
    glob_pattern: str,
    sql_template: str,
    params: Optional[List[Any]] = None,
) -> List[Dict[str, Any]]:
    """Run a bounded DuckDB SQL query against Parquet files safely.

    `sql_template` should reference `{source}` which is substituted with `read_parquet(...)`.
    """
    resolved = str(Path(glob_pattern))
    with open_bounded_duckdb() as conn:
        query = sql_template.format(source=f"read_parquet('{resolved.replace(chr(92), '/')}', union_by_name=true)")
        rel = conn.execute(query, params or [])
        cols = [d[0] for d in rel.description] if rel.description else []
        rows = rel.fetchall()
        return [dict(zip(cols, r)) for r in rows]

