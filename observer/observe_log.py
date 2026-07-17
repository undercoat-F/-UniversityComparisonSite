from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

try:
    import psycopg2
except Exception:  # pragma: no cover
    psycopg2 = None

try:
    from psycopg2.extras import Json
except Exception:  # pragma: no cover
    Json = None

from dataclass.dataclass import SeedTransformInput
from observer.observe_supervisor import ObserveStackItem


def _json_value(value: Any) -> Any:
    if Json is not None:
        return Json(value)
    return value


@dataclass
class ObserveRunLogRecord:
    external_run_id: int | None
    source_count: int
    observed_count: int = 0
    queued_count: int = 0
    dispatched_count: int = 0
    transformed_count: int = 0
    added_targets_count: int = 0
    error_count: int = 0
    status: str = "running"
    notes: str | None = None


class ObserveLogStore:
    def __init__(self, *, pg_dsn: str, schema_path: str) -> None:
        self.pg_dsn = (pg_dsn or "").strip()
        self.schema_path = schema_path
        self._conn: Any = None

    @classmethod
    def from_env(cls) -> "ObserveLogStore | None":
        enabled = os.getenv("OBSERVE_LOG_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off", ""}
        if not enabled:
            return None

        pg_dsn = (
            os.getenv("OBSERVE_LOG_POSTGRES_DSN", "").strip()
            or os.getenv("SEARCH_LOG_POSTGRES_DSN", "").strip()
            or os.getenv("QUEUE_LOG_POSTGRES_DSN", "").strip()
        )
        if not pg_dsn:
            return None

        schema_path = os.getenv("OBSERVE_LOG_SCHEMA_PATH", os.path.join("observer", "seed_observe_log_schema.sql"))
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

    def create_run(self, record: ObserveRunLogRecord) -> int:
        conn = self._connect()
        cur = conn.cursor()
        try:
            cur.execute(
                """
                INSERT INTO seed_observe_runs (
                    external_run_id,
                    source_count,
                    observed_count,
                    queued_count,
                    dispatched_count,
                    transformed_count,
                    added_targets_count,
                    error_count,
                    status,
                    notes
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    record.external_run_id,
                    int(record.source_count),
                    int(record.observed_count),
                    int(record.queued_count),
                    int(record.dispatched_count),
                    int(record.transformed_count),
                    int(record.added_targets_count),
                    int(record.error_count),
                    record.status,
                    record.notes,
                ),
            )
            run_id = int(cur.fetchone()[0])
            conn.commit()
            return run_id
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()

    def finish_run(self, run_id: int, record: ObserveRunLogRecord) -> None:
        conn = self._connect()
        cur = conn.cursor()
        try:
            cur.execute(
                """
                UPDATE seed_observe_runs
                   SET external_run_id = %s,
                       source_count = %s,
                       observed_count = %s,
                       queued_count = %s,
                       dispatched_count = %s,
                       transformed_count = %s,
                       added_targets_count = %s,
                       error_count = %s,
                       status = %s,
                       notes = %s,
                       finished_at = NOW()
                 WHERE id = %s
                """,
                (
                    record.external_run_id,
                    int(record.source_count),
                    int(record.observed_count),
                    int(record.queued_count),
                    int(record.dispatched_count),
                    int(record.transformed_count),
                    int(record.added_targets_count),
                    int(record.error_count),
                    record.status,
                    record.notes,
                    int(run_id),
                ),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()

    def insert_result(
        self,
        run_id: int,
        *,
        external_run_id: int | None,
        source_stage: str,
        item: ObserveStackItem,
        result: SeedTransformInput,
        request_log_count: int,
    ) -> None:
        conn = self._connect()
        cur = conn.cursor()
        page_analysis = item.page_analysis
        page_flags = {
            "table_list": bool(page_analysis.table_list),
            "search_form": bool(page_analysis.search_form),
            "profile": bool(page_analysis.profile),
            "text": bool(page_analysis.text),
        }
        try:
            cur.execute(
                """
                INSERT INTO seed_observe_results (
                    run_id,
                    external_run_id,
                    source_stage,
                    source_url,
                    source_domain,
                    source_page_type,
                    page_flags,
                    candidate_lines,
                    request_log_count,
                    university_names,
                    hit_count,
                    hits,
                    root_seed_urls,
                    detailed_seed_urls,
                    course_list_found,
                    recommended_depth,
                    duplicate_root_urls,
                    errors,
                    error_count,
                    api_type,
                    first_search_count,
                    internal_link_extracted_count,
                    fallback_executed,
                    api_usage_count,
                    search_queries
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    int(run_id),
                    external_run_id,
                    source_stage,
                    item.source_url,
                    result.source_domain,
                    page_analysis.content_type.value,
                    _json_value(page_flags),
                    _json_value(list(page_analysis.candidate_lines)),
                    int(request_log_count),
                    _json_value(list(result.university_names)),
                    int(len(result.hits)),
                    _json_value([
                        {
                            "query": hit.query,
                            "url": hit.url,
                            "title": hit.title,
                            "snippet": hit.snippet,
                            "score": hit.score,
                            "is_course_like": hit.is_course_like,
                            "search_form_detected": hit.search_form_detected,
                            "course_list_detected": hit.course_list_detected,
                        }
                        for hit in result.hits
                    ]),
                    _json_value(list(result.root_seed_urls)),
                    _json_value(list(result.detailed_seed_urls)),
                    bool(result.course_list_found),
                    int(result.recommended_depth),
                    _json_value(list(result.duplicate_root_urls)),
                    _json_value(list(result.errors)),
                    int(len(result.errors)),
                    result.api_type,
                    int(result.first_search_count),
                    int(result.internal_link_extracted_count),
                    bool(result.fallback_executed),
                    int(result.api_usage_count),
                    _json_value(list(result.search_queries)),
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