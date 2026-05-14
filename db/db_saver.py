#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
CSVファイルをPostgreSQLに投入するスクリプト（関数型）
スキーマ作成 -> CSV読み込み -> 正規形でINSERT/UPDATE
"""

import csv
import os
from pathlib import Path

import psycopg2
from psycopg2 import Error, sql
from dotenv import load_dotenv

load_dotenv(encoding="utf-8-sig")


def require_env(keys):
    """必須環境変数の存在を検証する。"""
    missing = [k for k in keys if not os.getenv(k)]
    if missing:
        raise EnvironmentError(f".envに必要な環境変数が設定されていません: {missing}")


def get_db_params_from_env():
    """DB接続パラメータを.envから取得する。"""
    require_env(["DB_HOST", "DB_NAME", "DB_USER", "DB_PASSWORD", "DB_PORT"])
    return {
        "host": os.getenv("DB_HOST"),
        "dbname": os.getenv("DB_NAME"),
        "user": os.getenv("DB_USER"),
        "password": os.getenv("DB_PASSWORD"),
        "port": int(os.getenv("DB_PORT")),
    }


def connect(db_params):
    """PostgreSQLに接続する。"""
    enc_candidates = [None, "UTF8", "SJIS"]

    for enc in enc_candidates:
        try:
            if enc:
                os.environ["PGCLIENTENCODING"] = enc
            conn = psycopg2.connect(**db_params)
            print(f"PostgreSQL接続成功: {db_params['dbname']}")
            return conn
        except UnicodeDecodeError as e:
            print(f"接続時デコードエラー（encoding={enc or 'default'}）: {e}")
            continue
        except Error as e:
            print(f"接続エラー: {e}")
            return None
        except Exception as e:
            print(f"予期しない接続エラー: {e}")
            return None

    print("接続失敗: 文字コード設定を切り替えても接続できませんでした。")
    return None


def ensure_database_exists(db_params):
    """接続先DBが無ければ作成する（管理DB: postgres に接続）。"""
    admin_params = dict(db_params)
    admin_params["dbname"] = "postgres"
    target_db = db_params["dbname"]

    conn = None
    cursor = None
    try:
        conn = psycopg2.connect(**admin_params)
        conn.autocommit = True
        cursor = conn.cursor()

        cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (target_db,))
        exists = cursor.fetchone() is not None

        if exists:
            print(f"DB確認: {target_db} は既に存在します")
        else:
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(target_db)))
            print(f"DB作成: {target_db} を新規作成しました")

        return True
    except Error as e:
        print(f"DB存在確認/作成エラー: {e}")
        return False
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


def disconnect(conn):
    """接続を切断する。"""
    if conn:
        conn.close()
        print("接続を閉じました")


def create_schema(conn):
    """正規形スキーマを作成し、重複制御に必要な制約/インデックスを準備する。"""
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS universities (
                id SERIAL PRIMARY KEY,
                name VARCHAR(255) NOT NULL UNIQUE,
                country VARCHAR(100),
                url TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS degree_programs (
                id SERIAL PRIMARY KEY,
                university_id INTEGER NOT NULL REFERENCES universities(id) ON DELETE CASCADE,
                program_name VARCHAR(500) NOT NULL,
                course_type VARCHAR(100),
                is_online BOOLEAN DEFAULT FALSE,
                source_url TEXT,
                last_seen TIMESTAMP,
                quality_flag VARCHAR(50) DEFAULT 'high',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS tuition_patterns (
                id SERIAL PRIMARY KEY,
                degree_level VARCHAR(50),
                amount DECIMAL(10, 2),
                currency VARCHAR(10),
                fee_type VARCHAR(50) DEFAULT 'tuition',
                tuition_type VARCHAR(30) DEFAULT 'unknown',
                amount_min DECIMAL(10, 2),
                amount_max DECIMAL(10, 2),
                normalized_monthly_amount DECIMAL(10, 2),
                normalization_note TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (degree_level, amount, currency, fee_type, tuition_type)
            );
            """
        )

        # 既存DBを段階移行できるよう、新列を追加してから制約を置き換える。
        cursor.execute("ALTER TABLE tuition_patterns ADD COLUMN IF NOT EXISTS tuition_type VARCHAR(30) DEFAULT 'unknown';")
        cursor.execute("ALTER TABLE tuition_patterns ADD COLUMN IF NOT EXISTS amount_min DECIMAL(10, 2);")
        cursor.execute("ALTER TABLE tuition_patterns ADD COLUMN IF NOT EXISTS amount_max DECIMAL(10, 2);")
        cursor.execute("ALTER TABLE tuition_patterns ADD COLUMN IF NOT EXISTS normalized_monthly_amount DECIMAL(10, 2);")
        cursor.execute("ALTER TABLE tuition_patterns ADD COLUMN IF NOT EXISTS normalization_note TEXT;")
        cursor.execute("UPDATE tuition_patterns SET tuition_type = 'unknown' WHERE tuition_type IS NULL;")
        cursor.execute(
            """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.table_constraints
                    WHERE table_name='tuition_patterns'
                      AND constraint_name='tuition_patterns_degree_level_amount_currency_fee_type_key'
                ) THEN
                    ALTER TABLE tuition_patterns
                    DROP CONSTRAINT tuition_patterns_degree_level_amount_currency_fee_type_key;
                END IF;
            END $$;
            """
        )
        cursor.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_tuition_patterns_v2
            ON tuition_patterns (degree_level, amount, currency, fee_type, tuition_type);
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS program_tuition_map (
                degree_program_id INTEGER NOT NULL REFERENCES degree_programs(id) ON DELETE CASCADE,
                tuition_pattern_id INTEGER NOT NULL REFERENCES tuition_patterns(id) ON DELETE CASCADE,
                PRIMARY KEY (degree_program_id, tuition_pattern_id)
            );
            """
        )

        # 既存データと今後のUPSERT整合性を取るため、NULLを埋める。
        cursor.execute("UPDATE degree_programs SET source_url = '' WHERE source_url IS NULL;")
        cursor.execute("UPDATE degree_programs SET course_type = '' WHERE course_type IS NULL;")
        cursor.execute("UPDATE degree_programs SET is_online = FALSE WHERE is_online IS NULL;")

        # 既存データに重複があるとUNIQUE INDEX作成に失敗するため先に正規化する。
        cursor.execute(
            """
            WITH ranked AS (
                SELECT
                    id,
                    ROW_NUMBER() OVER (
                        PARTITION BY university_id, source_url, program_name, course_type, is_online
                        ORDER BY id
                    ) AS rn
                FROM degree_programs
            )
            DELETE FROM degree_programs d
            USING ranked r
            WHERE d.id = r.id AND r.rn > 1;
            """
        )

        cursor.execute("ALTER TABLE degree_programs ALTER COLUMN source_url SET DEFAULT '';")
        cursor.execute("ALTER TABLE degree_programs ALTER COLUMN course_type SET DEFAULT '';")
        cursor.execute("ALTER TABLE degree_programs ALTER COLUMN is_online SET DEFAULT FALSE;")

        # URL再探索時の重複制御に使う自然キー。
        cursor.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_degree_program_natural_idx
            ON degree_programs (university_id, source_url, program_name, course_type, is_online);
            """
        )

        cursor.execute("CREATE INDEX IF NOT EXISTS idx_uni_name ON universities(name);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_prog_uni_id ON degree_programs(university_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_map_prog_id ON program_tuition_map(degree_program_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_map_pattern_id ON program_tuition_map(tuition_pattern_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_pattern_level ON tuition_patterns(degree_level);")

        conn.commit()
        print("スキーマ作成/更新完了")
        return True
    except Error as e:
        print(f"スキーマ作成エラー: {e}")
        conn.rollback()
        return False
    finally:
        cursor.close()

#正規化　判定エラー防止用のstrip,lower 
def parse_bool(raw):
    return str(raw).strip().lower() in ("1", "true", "t", "yes", "y")


def parse_optional_float(raw):
    text = str(raw).strip()
    if not text:
        return None

    normalized = text.lower()
    if normalized in ("none", "null", "nan", "n/a", "na", "-"):
        return None

    return float(text)


def parse_optional_timestamp(raw):
    text = str(raw).strip()
    if not text:
        return None
    if text.lower() in ("none", "null", "nan"):
        return None
    return text


def insert_universities_from_csv(conn, csv_path):
    """Universities CSV を投入し、csv_id -> db_id の対応を返す。"""
    cursor = conn.cursor()
    inserted = 0
    id_map = {}

    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("name", "").strip().startswith("#"):
                    continue

                csv_id = str(row.get("id", "")).strip()
                name = row.get("name", "").strip()
                if not name:
                    continue

                country = row.get("country", "").strip() or None
                url = row.get("url", "").strip() or None
                created_at = parse_optional_timestamp(row.get("created_at", ""))

                cursor.execute(
                    """
                    INSERT INTO universities (name, country, url, created_at, updated_at)
                    VALUES (%s, %s, %s, COALESCE(%s::timestamp, NOW()), NOW())
                    ON CONFLICT (name) DO UPDATE SET
                        country = EXCLUDED.country,
                        url = EXCLUDED.url,
                        updated_at = NOW()
                    RETURNING id;
                    """,
                    (name, country, url, created_at),
                )
                db_id = cursor.fetchone()[0]
                id_map[csv_id] = db_id
                inserted += 1

        conn.commit()
        print(f"universities: {inserted}件投入")
        return inserted, id_map
    except Error as e:
        print(f"universities CSV投入エラー: {e}")
        conn.rollback()
        return 0, {}
    finally:
        cursor.close()


def insert_programs_from_csv(conn, csv_path, university_id_map):
    """Degree Programs CSV を投入し、csv_id -> db_id の対応を返す。"""
    cursor = conn.cursor()
    inserted = 0
    skipped = 0
    id_map = {}

    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("program_name", "").strip().startswith("#"):
                    continue

                csv_id = str(row.get("id", "")).strip()
                csv_uni_id = str(row.get("university_id", "")).strip()
                db_uni_id = university_id_map.get(csv_uni_id)

                if db_uni_id is None:
                    skipped += 1
                    continue

                program_name = row.get("program_name", "").strip()
                if not program_name:
                    skipped += 1
                    continue

                course_type = row.get("course_type", "").strip()
                is_online = parse_bool(row.get("is_online", "0"))
                source_url = row.get("source_url", "").strip()
                last_seen = parse_optional_timestamp(row.get("last_seen", ""))
                quality_flag = row.get("quality_flag", "high").strip() or "high"

                cursor.execute(
                    """
                    INSERT INTO degree_programs
                    (university_id, program_name, course_type, is_online, source_url, last_seen, quality_flag)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (university_id, source_url, program_name, course_type, is_online)
                    DO UPDATE SET
                        last_seen = EXCLUDED.last_seen,
                        quality_flag = EXCLUDED.quality_flag
                    RETURNING id;
                    """,
                    (db_uni_id, program_name, course_type, is_online, source_url, last_seen, quality_flag),
                )
                db_id = cursor.fetchone()[0]
                id_map[csv_id] = db_id
                inserted += 1

        conn.commit()
        print(f"degree_programs: {inserted}件投入, {skipped}件スキップ")
        return inserted, id_map
    except Error as e:
        print(f"degree_programs CSV投入エラー: {e}")
        conn.rollback()
        return 0, {}
    finally:
        cursor.close()


def insert_patterns_from_csv(conn, csv_path):
    """Tuition Patterns CSV を投入し、csv_id -> db_id の対応を返す。"""
    cursor = conn.cursor()
    inserted = 0
    id_map = {}

    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                csv_id = str(row.get("id", "")).strip()
                degree_level = row.get("degree_level", "").strip() or None
                amount = parse_optional_float(row.get("amount", ""))
                currency = row.get("currency", "").strip() or None
                fee_type = row.get("fee_type", "tuition").strip() or "tuition"
                tuition_type = row.get("tuition_type", "unknown").strip() or "unknown"
                amount_min = parse_optional_float(row.get("amount_min", ""))
                amount_max = parse_optional_float(row.get("amount_max", ""))
                normalized_monthly_amount = parse_optional_float(row.get("normalized_monthly_amount", ""))
                normalization_note = row.get("normalization_note", "unknown_not_normalized").strip() or "unknown_not_normalized"

                cursor.execute(
                    """
                    INSERT INTO tuition_patterns
                    (degree_level, amount, currency, fee_type, tuition_type, amount_min, amount_max, normalized_monthly_amount, normalization_note)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (degree_level, amount, currency, fee_type, tuition_type)
                    DO UPDATE SET
                        amount_min = EXCLUDED.amount_min,
                        amount_max = EXCLUDED.amount_max,
                        normalized_monthly_amount = EXCLUDED.normalized_monthly_amount,
                        normalization_note = EXCLUDED.normalization_note
                    RETURNING id;
                    """,
                    (
                        degree_level,
                        amount,
                        currency,
                        fee_type,
                        tuition_type,
                        amount_min,
                        amount_max,
                        normalized_monthly_amount,
                        normalization_note,
                    ),
                )
                db_id = cursor.fetchone()[0]
                id_map[csv_id] = db_id
                inserted += 1

        conn.commit()
        print(f"tuition_patterns: {inserted}件投入")
        return inserted, id_map
    except Error as e:
        print(f"tuition_patterns CSV投入エラー: {e}")
        conn.rollback()
        return 0, {}
    finally:
        cursor.close()


def insert_map_from_csv(conn, csv_path, program_id_map, pattern_id_map):
    """Program Tuition Map CSV を投入（IDマッピング経由で整合性を維持）。"""
    cursor = conn.cursor()
    inserted = 0
    skipped = 0

    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                csv_program_id = str(row.get("degree_program_id", "")).strip()
                csv_pattern_id = str(row.get("tuition_pattern_id", "")).strip()

                db_program_id = program_id_map.get(csv_program_id)
                db_pattern_id = pattern_id_map.get(csv_pattern_id)

                if db_program_id is None or db_pattern_id is None:
                    skipped += 1
                    continue

                cursor.execute(
                    """
                    INSERT INTO program_tuition_map (degree_program_id, tuition_pattern_id)
                    VALUES (%s, %s)
                    ON CONFLICT (degree_program_id, tuition_pattern_id) DO NOTHING;
                    """,
                    (db_program_id, db_pattern_id),
                )
                inserted += 1

        conn.commit()
        print(f"program_tuition_map: {inserted}件投入, {skipped}件スキップ")
        return inserted
    except Error as e:
        print(f"program_tuition_map CSV投入エラー: {e}")
        conn.rollback()
        return 0
    finally:
        cursor.close()


def resolve_csv_dir(csv_dir):
    """CSVディレクトリを実行場所に依存せず解決する。"""
    input_path = Path(csv_dir)
    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent

    candidates = []
    if input_path.is_absolute():#絶対パスか否かの判定
        candidates.append(input_path)
    else:
        candidates.extend([
            Path.cwd() / input_path,
            script_dir / input_path,
            project_root / input_path,
        ])#相対パスの場合は、実行場所、スクリプト場所、プロジェクトルートからのパスを候補にする

    # 順序を維持したまま重複を除去
    unique_candidates = []
    seen = set()
    for p in candidates:
        rp = p.resolve()
        key = str(rp)
        if key not in seen:
            seen.add(key)
            unique_candidates.append(rp)

    for candidate in unique_candidates:
        if candidate.exists() and candidate.is_dir():
            return candidate

    tried = "\n  - " + "\n  - ".join(str(p) for p in unique_candidates)
    raise FileNotFoundError(
        "CSV出力ディレクトリが見つかりません。CSV_OUTPUT_DIR を確認してください。"
        f"\n探索先:{tried}"
    )


def load_all(csv_dir):
    """完全フロー：接続 -> スキーマ作成 -> CSV投入。"""
    db_params = get_db_params_from_env()

    if not ensure_database_exists(db_params):
        return False

    conn = connect(db_params)
    if not conn:
        return False

    try:
        if not create_schema(conn):
            return False

        csv_dir = resolve_csv_dir(csv_dir)
        uni_count, uni_id_map = insert_universities_from_csv(conn, csv_dir / "universities.csv")
        prog_count, prog_id_map = insert_programs_from_csv(conn, csv_dir / "degree_programs.csv", uni_id_map)
        pattern_count, pattern_id_map = insert_patterns_from_csv(conn, csv_dir / "tuition_patterns.csv")
        map_count = insert_map_from_csv(conn, csv_dir / "program_tuition_map.csv", prog_id_map, pattern_id_map)

        print("\n" + "=" * 50)
        print("DB投入完了")
        print(f"  - universities: {uni_count}件")
        print(f"  - degree_programs: {prog_count}件")
        print(f"  - tuition_patterns: {pattern_count}件")
        print(f"  - program_tuition_map: {map_count}件")
        print("=" * 50)
        return True
    finally:
        disconnect(conn)


def main():
    require_env(["CSV_OUTPUT_DIR"])
    csv_output_dir = os.getenv("CSV_OUTPUT_DIR")

    success = load_all(csv_output_dir)
    if success:
        print("\n全プロセス完了")
    else:
        print("\nエラーが発生しました")

if __name__ == "__main__":
    main()
