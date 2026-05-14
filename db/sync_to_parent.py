#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
↑python3 で実行することを明示
shebang（シバン）とエンコーディング宣言
"""

"""
開発ブランチ DB → 親ブランチ（本番）DB への同期スクリプト

用途：
  - 開発ブランチで ETL 完了後、本番ブランチへデータをコピー
  - データ検証・確認後、Railway デプロイで公開

実行：
  python db/sync_to_parent.py
  または
  GitHub Actions で自動実行
"""

import os
import sys
import psycopg2
from psycopg2 import Error
from dotenv import load_dotenv

load_dotenv(encoding="utf-8-sig")


def get_dev_db_params():
    """開発ブランチ DB 接続パラメータ"""
    return {
        "host": os.getenv("DB_HOST"),
        "dbname": os.getenv("DB_NAME"),
        "user": os.getenv("DB_USER"),
        "password": os.getenv("DB_PASSWORD"),
        "port": int(os.getenv("DB_PORT", 5432)),
        "sslmode": "require",
    }


def get_parent_db_params():
    """親ブランチ（本番）DB 接続パラメータ"""
    parent_owner_connection = os.getenv("PARENT_DB_OWNER_CONNECTION")
    if not parent_owner_connection:
        raise EnvironmentError(
            ".env に PARENT_DB_OWNER_CONNECTION が設定されていません\n"
            "例: postgresql://neondb_owner:password@host/dbname?sslmode=require"
        )
    
    # 接続文字列を parse （簡易版）
    from urllib.parse import urlparse
    parsed = urlparse(parent_owner_connection)
    
    return {
        "host": parsed.hostname,
        "dbname": parsed.path.lstrip("/"),
        "user": parsed.username,
        "password": parsed.password,
        "port": parsed.port or 5432,
        "sslmode": "require",
    }


def connect(db_params, name):
    """DB に接続する"""
    try:
        conn = psycopg2.connect(**db_params)
        print(f"✓ {name} 接続成功: {db_params['host']}")
        return conn
    except Error as e:
        print(f"✗ {name} 接続失敗: {e}")
        sys.exit(1)


def create_parent_schema(parent_conn):
    """親ブランチにスキーマを作成（初回実行時）"""
    cursor = parent_conn.cursor()
    try:
        # テーブル作成
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS universities (
                id SERIAL PRIMARY KEY,
                name VARCHAR(255) NOT NULL UNIQUE,
                country VARCHAR(100),
                url TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS degree_programs (
                id SERIAL PRIMARY KEY,
                university_id INTEGER NOT NULL REFERENCES universities(id) ON DELETE CASCADE,
                program_name VARCHAR(500) NOT NULL,
                course_type VARCHAR(100),
                is_online BOOLEAN DEFAULT FALSE,
                source_url TEXT,
                last_seen TIMESTAMP,
                quality_flag VARCHAR(50) DEFAULT 'low',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)#quality_flagは欠損の方が起きやすいから、lowから始める
        
        cursor.execute("""
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
        """)#decimalは、合計10桁、そのうち小数点以下が2桁という意味　floatは誤差が出やすいらしい
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS program_tuition_map (
                degree_program_id INTEGER NOT NULL REFERENCES degree_programs(id) ON DELETE CASCADE,
                tuition_pattern_id INTEGER NOT NULL REFERENCES tuition_patterns(id) ON DELETE CASCADE,
                PRIMARY KEY (degree_program_id, tuition_pattern_id)
            );
        """)# ON DELETE CASCADE 親が消えたら自動で子も消えるという指定
        
        parent_conn.commit()
        print("✓ 親ブランチのスキーマを作成/確認")
    except Error as e:
        parent_conn.rollback()
        print(f"✗ スキーマ作成失敗: {e}")
        raise


def truncate_parent_tables(parent_conn):
    """親テーブルのデータを削除（外部キー制約を考慮）"""
    cursor = parent_conn.cursor()
    try:
        # 外部キー制約を一時的に無効化
        cursor.execute("SET CONSTRAINTS ALL DEFERRED;")
        
        # テーブル削除（順序重要）
        cursor.execute("DELETE FROM program_tuition_map;")
        cursor.execute("DELETE FROM tuition_patterns;")
        cursor.execute("DELETE FROM degree_programs;")
        cursor.execute("DELETE FROM universities;")
        
        # シーケンスもリセット（存在確認）
        try:
            cursor.execute("ALTER SEQUENCE universities_id_seq RESTART WITH 1;")
            cursor.execute("ALTER SEQUENCE degree_programs_id_seq RESTART WITH 1;")
            cursor.execute("ALTER SEQUENCE tuition_patterns_id_seq RESTART WITH 1;")
            #自動裁判の番号を再び１から振りなおすということ
            #TRUNCATE TABLE universities RESTART IDENTITY; みたいな書き方もあるらしい？
        except Error:
            # シーケンスが存在しない可能性
            pass
        
        parent_conn.commit()
        print("✓ 親テーブルをクリア（DELETE）")
    except Error as e:
        parent_conn.rollback()
        print(f"✗ DELETE 失敗: {e}")
        raise


def copy_table(dev_conn, parent_conn, table_name):
    """開発 DB → 親 DB のテーブルをコピー"""
    try:
        # 開発 DB からデータ読み込み
        dev_cursor = dev_conn.cursor()
        dev_cursor.execute(f"SELECT * FROM {table_name};")
        rows = dev_cursor.fetchall()
        col_description = dev_cursor.description
        columns = [desc[0] for desc in col_description]
        
        if not rows:
            print(f"  {table_name}: データなし（スキップ）")
            return 0
        
        # 親 DB へ INSERT
        parent_cursor = parent_conn.cursor()
        
        # COPY コマンド使用（高速）らしい？
        # ただし簡易版として INSERT で実装
        placeholders = ", ".join(["%s"] * len(columns))
        col_names = ", ".join(columns)
        insert_sql = f"INSERT INTO {table_name} ({col_names}) VALUES ({placeholders})"
        
        parent_cursor.executemany(insert_sql, rows)
        parent_conn.commit()
        
        print(f"  ✓ {table_name}: {len(rows)} 件コピー")
        return len(rows)
    
    except Error as e:
        parent_conn.rollback()
        print(f"  ✗ {table_name} コピー失敗: {e}")
        raise


def verify_sync(dev_conn, parent_conn):
    """同期結果を検証"""
    tables = ["universities", "degree_programs", "tuition_patterns", "program_tuition_map"]
    
    print("\n📊 同期結果検証:")
    all_match = True
    
    for table in tables:
        dev_cursor = dev_conn.cursor()
        parent_cursor = parent_conn.cursor()
        
        dev_cursor.execute(f"SELECT COUNT(*) FROM {table};")
        dev_count = dev_cursor.fetchone()[0]
        
        parent_cursor.execute(f"SELECT COUNT(*) FROM {table};")
        parent_count = parent_cursor.fetchone()[0]
        
        match = "✓" if dev_count == parent_count else "✗" #ifがTrueなら✓、Falseなら✗を表示（三項演算子というらしい）
        print(f"  {match} {table}: 開発={dev_count}, 親={parent_count}")
        
        if dev_count != parent_count:
            all_match = False
    
    return all_match


def main():
    print("=" * 70)
    print("📤 開発ブランチ → 親ブランチ DB 同期")
    print("=" * 70 + "\n")
    
    # 接続
    dev_params = get_dev_db_params()
    parent_params = get_parent_db_params()
    
    dev_conn = connect(dev_params, "開発 DB")
    parent_conn = connect(parent_params, "親 DB（本番）")
    
    try:
        # スキーマ作成（初回実行時）
        print("\n📐 スキーマ確認/作成...")
        create_parent_schema(parent_conn)
        
        # 親テーブルクリア
        print("\n🗑️  親テーブルをクリア...")
        truncate_parent_tables(parent_conn)
        
        # テーブルコピー（順序重要）
        print("\n📋 テーブルをコピー...")
        total_copied = 0
        for table in ["universities", "degree_programs", "tuition_patterns", "program_tuition_map"]:
            total_copied += copy_table(dev_conn, parent_conn, table)
        
        # 検証
        print("\n" + "=" * 70)
        is_valid = verify_sync(dev_conn, parent_conn)
        
        if is_valid:
            print("\n✅ 同期完了！ 親 DB が最新です。")
        else:
            print("\n⚠️  警告: データ数が一致しません。確認してください。")
        
        print(f"📊 合計 {total_copied} 件のレコードをコピー")
        print("=" * 70)
        
    except Exception as e:
        print(f"\n❌ エラー発生: {e}")
        sys.exit(1)
    finally:
        dev_conn.close()
        parent_conn.close()


if __name__ == "__main__":
    main()
