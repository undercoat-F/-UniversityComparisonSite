#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
seed_observe_results の品質ゲート判定ツール。

2つの入力モードをサポート:
1) SQLモード: PostgreSQL の seed_observe_results を直接読む
2) CSVモード: seed_observe_results 相当のCSVを読む

主な判定項目(デフォルト):
- root_seed_urls が1件以上ある行の割合 >= 0.70
- 致命エラー行率 <= 0.20
- 平均 API 使用回数 <= 200
- PDF 行がある場合、PDF 行で致命エラーが0

使い方例:
  # SQL (最新run)
  python check_quality_gate.py --mode sql

  # SQL (run_id指定)
  python check_quality_gate.py --mode sql --run-id 13

  # CSV
  python check_quality_gate.py --mode csv --csv-path docs/seed_observe_results.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Iterable


DEFAULT_FATAL_ERROR_KEYWORDS = (
    "BRAVE_API_KEY is not set",
    "query=",
    "fallback_query=",
    "search_log_write_failed",
    "sitemap_fetch_failed",
    "sitemap_robots_failed",
    "probe_sync_server_error",
    "probe_status_server_error",
    "probe_httpx_failed",
    "internal_extract",
    "internal_probe_sync",
    "internal_probe_httpx_failed",
    "internal_probe_status_server_error",
)


@dataclass
class RowRecord:
    source_url: str
    source_page_type: str
    hit_count: int
    root_seed_count: int
    detailed_seed_count: int
    api_usage_count: int
    errors: list[str]


@dataclass
class GateConfig:
    min_success_rate: float
    max_fatal_error_rate: float
    max_avg_api_usage: float
    require_pdf_no_fatal: bool
    fatal_error_keywords: tuple[str, ...]


@dataclass
class GateResult:
    total_rows: int
    success_rows: int
    success_rate: float
    fatal_rows: int
    fatal_error_rate: float
    avg_api_usage: float
    pdf_rows: int
    pdf_fatal_rows: int
    passed: bool


def _to_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, (int, float)):
            return int(value)
        text = str(value).strip()
        if text == "":
            return default
        return int(float(text))
    except Exception:
        return default


def _parse_json_like(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (list, dict)):
        return value
    text = str(value).strip()
    if not text:
        return None
    # psycopg2 が返す Python list/dict 文字列にもある程度対応
    try:
        return json.loads(text)
    except Exception:
        # シングルクオートの配列文字列などを救う簡易処理
        normalized = text.replace("'", '"')
        try:
            return json.loads(normalized)
        except Exception:
            return None


def _as_list(value: Any) -> list[Any]:
    parsed = _parse_json_like(value)
    if isinstance(parsed, list):
        return parsed
    return []


def _as_error_list(value: Any) -> list[str]:
    raw_list = _as_list(value)
    result: list[str] = []
    for item in raw_list:
        if item is None:
            continue
        result.append(str(item))
    return result


def _build_row_record(raw: dict[str, Any]) -> RowRecord:
    roots = _as_list(raw.get("root_seed_urls"))
    detailed = _as_list(raw.get("detailed_seed_urls"))
    errors = _as_error_list(raw.get("errors"))

    return RowRecord(
        source_url=str(raw.get("source_url") or ""),
        source_page_type=str(raw.get("source_page_type") or "").lower(),
        hit_count=_to_int(raw.get("hit_count"), 0),
        root_seed_count=len(roots),
        detailed_seed_count=len(detailed),
        api_usage_count=_to_int(raw.get("api_usage_count"), 0),
        errors=errors,
    )


def _contains_fatal_error(errors: list[str], keywords: tuple[str, ...]) -> bool:
    lowered = [e.lower() for e in errors]
    for key in keywords:
        token = key.lower()
        if any(token in err for err in lowered):
            return True
    return False


def evaluate_quality_gate(rows: Iterable[RowRecord], config: GateConfig) -> GateResult:
    row_list = list(rows)
    total = len(row_list)

    if total == 0:
        return GateResult(
            total_rows=0,
            success_rows=0,
            success_rate=0.0,
            fatal_rows=0,
            fatal_error_rate=0.0,
            avg_api_usage=0.0,
            pdf_rows=0,
            pdf_fatal_rows=0,
            passed=False,
        )

    success_rows = sum(1 for r in row_list if r.root_seed_count > 0)
    fatal_rows = sum(1 for r in row_list if _contains_fatal_error(r.errors, config.fatal_error_keywords))
    api_total = sum(r.api_usage_count for r in row_list)

    pdf_rows = [r for r in row_list if r.source_page_type == "pdf"]
    pdf_fatal_rows = sum(1 for r in pdf_rows if _contains_fatal_error(r.errors, config.fatal_error_keywords))

    success_rate = success_rows / total
    fatal_error_rate = fatal_rows / total
    avg_api_usage = api_total / total

    passed = (
        success_rate >= config.min_success_rate
        and fatal_error_rate <= config.max_fatal_error_rate
        and avg_api_usage <= config.max_avg_api_usage
        and (not config.require_pdf_no_fatal or (len(pdf_rows) == 0 or pdf_fatal_rows == 0))
    )

    return GateResult(
        total_rows=total,
        success_rows=success_rows,
        success_rate=success_rate,
        fatal_rows=fatal_rows,
        fatal_error_rate=fatal_error_rate,
        avg_api_usage=avg_api_usage,
        pdf_rows=len(pdf_rows),
        pdf_fatal_rows=pdf_fatal_rows,
        passed=passed,
    )


def load_rows_from_csv(csv_path: str) -> list[RowRecord]:
    path = Path(csv_path)
    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError("JSON は配列形式である必要があります")
        return [_build_row_record(item) for item in payload if isinstance(item, dict)]

    rows: list[RowRecord] = []
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for raw in reader:
            rows.append(_build_row_record(raw))
    return rows


def _resolve_sql_dsn(cli_dsn: str | None) -> str:
    if cli_dsn and cli_dsn.strip():
        return cli_dsn.strip()
    env_dsn = (
        os.getenv("OBSERVE_LOG_POSTGRES_DSN", "").strip()
        or os.getenv("SEARCH_LOG_POSTGRES_DSN", "").strip()
        or os.getenv("QUEUE_LOG_POSTGRES_DSN", "").strip()
    )
    return env_dsn


def load_rows_from_sql(dsn: str, run_id: int | None = None) -> list[RowRecord]:
    try:
        import psycopg2  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("psycopg2 が必要です。requirements を確認してください。") from exc

    if not dsn:
        raise ValueError("DSN が空です。--dsn か環境変数 OBSERVE_LOG_POSTGRES_DSN などを設定してください。")

    query = """
        SELECT
            source_url,
            source_page_type,
            hit_count,
            root_seed_urls,
            detailed_seed_urls,
            api_usage_count,
            errors
        FROM seed_observe_results
    """
    params: list[Any] = []

    if run_id is not None:
        query += " WHERE run_id = %s"
        params.append(run_id)
    else:
        query += " WHERE run_id = (SELECT MAX(run_id) FROM seed_observe_results)"

    query += " ORDER BY id"

    rows: list[RowRecord] = []
    with psycopg2.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            cols = [desc[0] for desc in cur.description]
            for rec in cur.fetchall():
                raw = dict(zip(cols, rec))
                rows.append(_build_row_record(raw))
    return rows


def print_report(result: GateResult, config: GateConfig) -> None:
    print("=" * 72)
    print("Observer Quality Gate")
    print("=" * 72)
    print(f"total_rows            : {result.total_rows}")
    print(f"success_rows          : {result.success_rows}")
    print(f"success_rate          : {result.success_rate:.3f} (threshold >= {config.min_success_rate:.3f})")
    print(f"fatal_rows            : {result.fatal_rows}")
    print(f"fatal_error_rate      : {result.fatal_error_rate:.3f} (threshold <= {config.max_fatal_error_rate:.3f})")
    print(f"avg_api_usage         : {result.avg_api_usage:.2f} (threshold <= {config.max_avg_api_usage:.2f})")
    print(f"pdf_rows              : {result.pdf_rows}")
    print(f"pdf_fatal_rows        : {result.pdf_fatal_rows}")
    print(f"require_pdf_no_fatal  : {config.require_pdf_no_fatal}")
    print("-" * 72)
    print("RESULT: PASS" if result.passed else "RESULT: FAIL")
    print("=" * 72)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="seed_observe_results の合格条件を判定")
    parser.add_argument("--mode", choices=["sql", "csv"], required=True, help="入力モード")
    parser.add_argument("--csv-path", default="", help="CSVファイルパス (--mode csv で必須)")
    parser.add_argument("--dsn", default="", help="PostgreSQL DSN (--mode sql で省略時は環境変数から解決)")
    parser.add_argument("--run-id", type=int, default=None, help="対象 run_id (--mode sql、未指定なら最新)")

    parser.add_argument("--min-success-rate", type=float, default=0.70)
    parser.add_argument("--max-fatal-error-rate", type=float, default=0.20)
    parser.add_argument("--max-avg-api-usage", type=float, default=200.0)
    parser.add_argument("--require-pdf-no-fatal", action="store_true")

    parser.add_argument(
        "--fatal-keyword",
        action="append",
        default=[],
        help="致命エラー判定キーワード（複数指定可）。未指定ならデフォルト集合を使用",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    fatal_keywords = tuple(args.fatal_keyword) if args.fatal_keyword else DEFAULT_FATAL_ERROR_KEYWORDS
    config = GateConfig(
        min_success_rate=args.min_success_rate,
        max_fatal_error_rate=args.max_fatal_error_rate,
        max_avg_api_usage=args.max_avg_api_usage,
        require_pdf_no_fatal=bool(args.require_pdf_no_fatal),
        fatal_error_keywords=fatal_keywords,
    )

    try:
        if args.mode == "csv":
            if not args.csv_path:
                raise ValueError("--mode csv の場合は --csv-path が必要です")
            rows = load_rows_from_csv(args.csv_path)
        else:
            dsn = _resolve_sql_dsn(args.dsn)
            rows = load_rows_from_sql(dsn, run_id=args.run_id)

        result = evaluate_quality_gate(rows, config)
        print_report(result, config)
        return 0 if result.passed else 2
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
