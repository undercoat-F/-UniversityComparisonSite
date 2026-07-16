from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

try:
    import psycopg2
except Exception:  # pragma: no cover
    psycopg2 = None
from dataclass.dataclass import SearchRunLogRecord

#不明　おそらくログやデータベースの操作に関するクラスや関数の設定を環境変数で設定するための関数
class SearchLogStore:
    def __init__(self, *, pg_dsn: str, schema_path: str) -> None:
        self.pg_dsn = (pg_dsn or "").strip()
        self.schema_path = schema_path
        self._conn: Any = None

    @classmethod
    def from_env(cls) -> "SearchLogStore | None":
        enabled = os.getenv("SEARCH_LOG_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off", ""}
        if not enabled:
            return None

        pg_dsn = os.getenv("SEARCH_LOG_POSTGRES_DSN", "").strip() or os.getenv("QUEUE_LOG_POSTGRES_DSN", "").strip()
        if not pg_dsn:
            return None

        schema_path = os.getenv("SEARCH_LOG_SCHEMA_PATH", os.path.join("ETL", "search_log_schema.sql"))
        return cls(pg_dsn=pg_dsn, schema_path=schema_path)

    def _connect(self):
        if self._conn is not None:
            return self._conn
        if not self.pg_dsn:
            raise ValueError("pg_dsn is required")
        if psycopg2 is None:
            raise RuntimeError("psycopg2 is not installed. Install psycopg2-binary.")
        self._conn = psycopg2.connect(self.pg_dsn)
        self._conn.autocommit = False
        return self._conn

    def init_db(self) -> None:
        with open(self.schema_path, "r", encoding="utf-8") as f:
            schema_sql = f.read()
        conn = self._connect()
        cur = conn.cursor()
        try:
            cur.execute(schema_sql)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()

    def insert_run_log(self, record: SearchRunLogRecord) -> None:
        conn = self._connect()
        cur = conn.cursor()
        try:
            cur.execute(
                """
                INSERT INTO seed_search_runs (
                    run_id,
                    source_stage,
                    source_url,
                    source_domain,
                    api_type,
                    first_search_count,
                    internal_link_extracted_count,
                    fallback_executed,
                    api_usage_count
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    int(record.run_id) if record.run_id is not None else None,
                    record.source_stage,
                    record.source_url,
                    record.source_domain,
                    record.api_type,
                    int(record.first_search_count),
                    int(record.internal_link_extracted_count),
                    bool(record.fallback_executed),
                    int(record.api_usage_count),
                ),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
