from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Iterable

try:
    import psycopg2
except Exception:  # pragma: no cover
    psycopg2 = None

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from db.schema_config import render_sql_template

SCHEMA_DIR = PROJECT_ROOT / "db" / "schema"

SCHEMA_FILES = {
    "observer": SCHEMA_DIR / "observer_schema.sql",
    "etl": SCHEMA_DIR / "etl_schema.sql",
    "public": SCHEMA_DIR / "public_schema.sql",
}

DEFAULT_DSN_ENV_ORDER = [
    "PARENT_DB_OWNER_CONNECTION",
]


def _read_and_render_sql(path: Path) -> str:
    sql_text = path.read_text(encoding="utf-8")
    return render_sql_template(sql_text)


def _resolve_dsn(dsn: str, dsn_env_order: Iterable[str]) -> tuple[str, str]:
    if dsn.strip():
        return dsn.strip(), "--dsn"

    for env_name in dsn_env_order:
        value = os.getenv(env_name, "").strip()
        if value:
            return value, env_name

    env_names = ", ".join(dsn_env_order)
    raise RuntimeError(
        "DSN が見つかりません。--dsn を指定するか、次の環境変数を設定してください: "
        f"{env_names}"
    )


def _write_rendered_sql(write_dir: Path, ordered_schemas: list[str], rendered: dict[str, str]) -> None:
    write_dir.mkdir(parents=True, exist_ok=True)
    for index, schema_name in enumerate(ordered_schemas, start=1):
        out_path = write_dir / f"{index:02d}_{schema_name}_schema.rendered.sql"
        out_path.write_text(rendered[schema_name], encoding="utf-8")
        print(f"[WRITE] {out_path}")


def _apply_sql_bundle(dsn: str, ordered_schemas: list[str], rendered: dict[str, str]) -> None:
    if psycopg2 is None:
        raise RuntimeError("psycopg2 が必要です。必要なら '.venv' の Python で実行してください。")

    conn = psycopg2.connect(dsn)
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            for schema_name in ordered_schemas:
                print(f"[APPLY] {schema_name} schema")
                cur.execute(rendered[schema_name])
        conn.commit()
        print("[DONE] schema bundle applied successfully")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="db/schema の統合 SQL を .env 展開して順次適用します。"
    )
    parser.add_argument(
        "--schemas",
        nargs="+",
        choices=list(SCHEMA_FILES.keys()),
        default=["observer", "etl", "public"],
        help="適用するスキーマ順序。デフォルト: observer etl public",
    )
    parser.add_argument(
        "--dsn",
        default="",
        help="接続DSN。未指定時は --dsn-env-order の先頭から自動解決",
    )
    parser.add_argument(
        "--dsn-env-order",
        nargs="+",
        default=DEFAULT_DSN_ENV_ORDER,
        help="DSN 自動解決に使う環境変数の優先順",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="DBへ適用せず、レンダリングのみ実行",
    )
    parser.add_argument(
        "--write-rendered-dir",
        default="",
        help="レンダリング後SQLを書き出すディレクトリ",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    ordered_schemas: list[str] = args.schemas
    rendered: dict[str, str] = {}

    for schema_name in ordered_schemas:
        path = SCHEMA_FILES[schema_name]
        if not path.exists():
            raise FileNotFoundError(f"Schema file not found: {path}")
        rendered[schema_name] = _read_and_render_sql(path)
        print(f"[RENDER] {schema_name}: {path}")

    if args.write_rendered_dir.strip():
        _write_rendered_sql(Path(args.write_rendered_dir.strip()), ordered_schemas, rendered)

    dsn, source = _resolve_dsn(args.dsn, args.dsn_env_order)
    print(f"[DSN] source={source}")

    if args.dry_run:
        print("[DRY-RUN] SQL was rendered. No DB changes applied.")
        return 0

    _apply_sql_bundle(dsn, ordered_schemas, rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
