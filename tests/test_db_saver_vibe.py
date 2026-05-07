#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
db_saver.py の簡易ユニットテスト
SQLite インメモリDBを使ってロジックを検証する。
（PostgreSQL 不要）

注意: psycopg2 の SQL文は %s プレースホルダーを使うが、
      sqlite3 は ? を使うため、テスト用に差し替えた軽量 stub を用いる。
"""

import sys
import os
import csv
import json
import tempfile
import sqlite3
import unittest
from pathlib import Path
from datetime import datetime

# ---------- テスト対象の import より先に stub を注入 ----------
# psycopg2 の代わりに sqlite3 ベースの stub を提供する

class _StubCursor:
    def __init__(self, conn):
        self._conn = conn
        self._cur = conn.connection.cursor()

    def execute(self, sql, params=None):
        # %s → ? に変換（単純置換）
        sql_lite = sql.replace('%s', '?')
        # PostgreSQL 固有の構文を SQLite 向けに変換
        sql_lite = sql_lite.replace('SERIAL PRIMARY KEY', 'INTEGER PRIMARY KEY AUTOINCREMENT')
        sql_lite = sql_lite.replace('ON CONFLICT (name) DO UPDATE SET', 'ON CONFLICT(name) DO UPDATE SET')
        sql_lite = sql_lite.replace('ON CONFLICT (id) DO UPDATE SET', 'ON CONFLICT(id) DO UPDATE SET')
        sql_lite = sql_lite.replace(
            'ON CONFLICT (degree_level, amount, currency, fee_type) DO NOTHING',
            'ON CONFLICT(degree_level, amount, currency, fee_type) DO NOTHING'
        )
        sql_lite = sql_lite.replace(
            'ON CONFLICT (degree_program_id, tuition_pattern_id) DO NOTHING',
            'ON CONFLICT(degree_program_id, tuition_pattern_id) DO NOTHING'
        )
        sql_lite = sql_lite.replace('DEFAULT CURRENT_TIMESTAMP', 'DEFAULT (datetime(\'now\'))')
        sql_lite = sql_lite.replace('CREATE INDEX IF NOT EXISTS', '-- INDEX')
        sql_lite = sql_lite.replace('SELECT 1 FROM pg_database WHERE datname =', 'SELECT 1 WHERE 1=')
        sql_lite = sql_lite.replace('REFERENCES universities(id) ON DELETE CASCADE', '')
        sql_lite = sql_lite.replace('REFERENCES degree_programs(id) ON DELETE CASCADE', '')
        sql_lite = sql_lite.replace('REFERENCES tuition_patterns(id) ON DELETE CASCADE', '')
        if params:
            self._cur.execute(sql_lite, params)
        else:
            self._cur.execute(sql_lite)

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()

    def close(self):
        self._cur.close()


class _StubConn:
    def __init__(self):
        self.connection = sqlite3.connect(':memory:', check_same_thread=False)
        self.autocommit = False

    def cursor(self):
        return _StubCursor(self)

    def commit(self):
        self.connection.commit()

    def rollback(self):
        self.connection.rollback()

    def close(self):
        self.connection.close()


# psycopg2 stub モジュール
import types, sys as _sys
_psycopg2 = types.ModuleType('psycopg2')
_stub_conn = None  # テストケースごとに差し替える

def _stub_connect(**kwargs):
    return _stub_conn

_psycopg2.connect = lambda **kwargs: _stub_connect(**kwargs)
_psycopg2.Error = Exception

_sql_mod = types.ModuleType('psycopg2.sql')
class _Identifier:
    def __init__(self, v): self.v = v
class _SQL:
    def __init__(self, s): self.s = s
    def format(self, ident): return _SQL(self.s.replace('{}', ident.v))
_sql_mod.Identifier = _Identifier
_sql_mod.SQL = _SQL
_psycopg2.sql = _sql_mod

_sys.modules['psycopg2'] = _psycopg2
_sys.modules['psycopg2.sql'] = _sql_mod

# dotenv stub
_dotenv = types.ModuleType('dotenv')
_dotenv.load_dotenv = lambda *a, **kw: None
_sys.modules['dotenv'] = _dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'db'))
import db_saver

# ---------- テスト用CSV生成ヘルパー ----------
SAMPLE_UNIVERSITIES = [
    {'id': '1', 'name': 'University of Edinburgh', 'country': 'UK',
     'url': 'https://study.ed.ac.uk', 'created_at': '2026-01-01 00:00:00'},
]

SAMPLE_PROGRAMS = [
    {'id': '1', 'university_id': '1', 'program_name': 'Informatics MSc',
     'course_type': 'computer_science', 'is_online': '0',
     'source_url': 'https://study.ed.ac.uk/pg/123', 'last_seen': '2026-01-01 00:00:00',
     'quality_flag': 'high'},
    {'id': '2', 'university_id': '1', 'program_name': 'History MA',
     'course_type': 'humanities', 'is_online': '0',
     'source_url': 'https://study.ed.ac.uk/pg/456', 'last_seen': '2026-01-01 00:00:00',
     'quality_flag': 'high'},
]

SAMPLE_PATTERNS = [
    {'id': '1', 'degree_level': 'Master', 'amount': '29400',
     'currency': 'GBP', 'fee_type': 'tuition'},
    {'id': '2', 'degree_level': 'PhD', 'amount': '5000',
     'currency': 'GBP', 'fee_type': 'tuition'},
]

SAMPLE_MAP = [
    {'degree_program_id': '1', 'tuition_pattern_id': '1'},
    {'degree_program_id': '2', 'tuition_pattern_id': '1'},
]


def _write_csv(path, fieldnames, rows):
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


class TestDbSaverWithSqlite(unittest.TestCase):

    def setUp(self):
        global _stub_conn
        # テストごとに新しいインメモリDBを作成
        _stub_conn = _StubConn()
        _psycopg2.connect = lambda **kwargs: _stub_conn

        self.saver = db_saver.DegreeDatabaseSaver()
        self.saver.conn = _stub_conn

        # 一時CSVディレクトリを準備
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        _stub_conn.close()

    def _create_schema_sqlite(self):
        """SQLite 向けに手動でスキーマを作成する"""
        c = _stub_conn.connection.cursor()
        c.executescript("""
            CREATE TABLE IF NOT EXISTS universities (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                country TEXT,
                url TEXT,
                created_at TEXT,
                updated_at TEXT
            );
            CREATE TABLE IF NOT EXISTS degree_programs (
                id INTEGER PRIMARY KEY,
                university_id INTEGER NOT NULL,
                program_name TEXT NOT NULL,
                course_type TEXT,
                is_online INTEGER DEFAULT 0,
                source_url TEXT,
                last_seen TEXT,
                quality_flag TEXT DEFAULT 'high',
                created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS tuition_patterns (
                id INTEGER PRIMARY KEY,
                degree_level TEXT,
                amount REAL,
                currency TEXT,
                fee_type TEXT DEFAULT 'tuition',
                created_at TEXT,
                UNIQUE (degree_level, amount, currency, fee_type)
            );
            CREATE TABLE IF NOT EXISTS program_tuition_map (
                degree_program_id INTEGER NOT NULL,
                tuition_pattern_id INTEGER NOT NULL,
                PRIMARY KEY (degree_program_id, tuition_pattern_id)
            );
        """)
        _stub_conn.connection.commit()

    def test_insert_universities(self):
        self._create_schema_sqlite()
        csv_path = Path(self.tmpdir) / 'universities.csv'
        _write_csv(csv_path, ['id', 'name', 'country', 'url', 'created_at'], SAMPLE_UNIVERSITIES)

        count = self.saver.insert_universities_from_csv(str(csv_path))
        self.assertEqual(count, 1)

        cur = _stub_conn.connection.cursor()
        cur.execute("SELECT name, country FROM universities")
        rows = cur.fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "University of Edinburgh")
        self.assertEqual(rows[0][1], "UK")

    def test_insert_programs(self):
        self._create_schema_sqlite()
        # universities を先に入れておく
        uni_csv = Path(self.tmpdir) / 'universities.csv'
        _write_csv(uni_csv, ['id', 'name', 'country', 'url', 'created_at'], SAMPLE_UNIVERSITIES)
        self.saver.insert_universities_from_csv(str(uni_csv))

        prog_csv = Path(self.tmpdir) / 'degree_programs.csv'
        _write_csv(prog_csv,
                   ['id', 'university_id', 'program_name', 'course_type',
                    'is_online', 'source_url', 'last_seen', 'quality_flag'],
                   SAMPLE_PROGRAMS)
        count = self.saver.insert_programs_from_csv(str(prog_csv))
        self.assertEqual(count, 2)

        cur = _stub_conn.connection.cursor()
        cur.execute("SELECT COUNT(*) FROM degree_programs")
        self.assertEqual(cur.fetchone()[0], 2)

    def test_insert_patterns_deduplication(self):
        """同じパターンを2回 INSERT → ON CONFLICT DO NOTHING で1件のみ残る"""
        self._create_schema_sqlite()
        patterns_csv = Path(self.tmpdir) / 'tuition_patterns.csv'
        dup_patterns = SAMPLE_PATTERNS + [
            {'id': '3', 'degree_level': 'Master', 'amount': '29400',
             'currency': 'GBP', 'fee_type': 'tuition'},  # 重複
        ]
        _write_csv(patterns_csv, ['id', 'degree_level', 'amount', 'currency', 'fee_type'], dup_patterns)
        count = self.saver.insert_patterns_from_csv(str(patterns_csv))
        # insert_patterns_from_csv は CSV 行数を返す（重複含む）
        self.assertEqual(count, 3)

        cur = _stub_conn.connection.cursor()
        cur.execute("SELECT COUNT(*) FROM tuition_patterns")
        # DB に実際に入るのは2件（重複は DO NOTHING）
        self.assertEqual(cur.fetchone()[0], 2)

    def test_insert_map(self):
        self._create_schema_sqlite()
        # 依存テーブルを先に作成
        uni_csv = Path(self.tmpdir) / 'universities.csv'
        prog_csv = Path(self.tmpdir) / 'degree_programs.csv'
        pat_csv = Path(self.tmpdir) / 'tuition_patterns.csv'
        _write_csv(uni_csv, ['id', 'name', 'country', 'url', 'created_at'], SAMPLE_UNIVERSITIES)
        _write_csv(prog_csv,
                   ['id', 'university_id', 'program_name', 'course_type',
                    'is_online', 'source_url', 'last_seen', 'quality_flag'], SAMPLE_PROGRAMS)
        _write_csv(pat_csv, ['id', 'degree_level', 'amount', 'currency', 'fee_type'], SAMPLE_PATTERNS)
        self.saver.insert_universities_from_csv(str(uni_csv))
        self.saver.insert_programs_from_csv(str(prog_csv))
        self.saver.insert_patterns_from_csv(str(pat_csv))

        map_csv = Path(self.tmpdir) / 'program_tuition_map.csv'
        _write_csv(map_csv, ['degree_program_id', 'tuition_pattern_id'], SAMPLE_MAP)
        count = self.saver.insert_map_from_csv(str(map_csv))
        self.assertEqual(count, 2)

        cur = _stub_conn.connection.cursor()
        cur.execute("SELECT COUNT(*) FROM program_tuition_map")
        self.assertEqual(cur.fetchone()[0], 2)

    def test_is_online_bool_conversion(self):
        """is_online カラムが True/False/0/1 いずれでも正しく変換されるか"""
        self._create_schema_sqlite()
        uni_csv = Path(self.tmpdir) / 'universities.csv'
        _write_csv(uni_csv, ['id', 'name', 'country', 'url', 'created_at'], SAMPLE_UNIVERSITIES)
        self.saver.insert_universities_from_csv(str(uni_csv))

        varied_programs = [
            {'id': '10', 'university_id': '1', 'program_name': 'Online MSc',
             'course_type': 'general', 'is_online': 'true',
             'source_url': '', 'last_seen': '', 'quality_flag': 'high'},
            {'id': '11', 'university_id': '1', 'program_name': 'Campus BSc',
             'course_type': 'general', 'is_online': '0',
             'source_url': '', 'last_seen': '', 'quality_flag': 'high'},
        ]
        prog_csv = Path(self.tmpdir) / 'degree_programs_bool.csv'
        _write_csv(prog_csv,
                   ['id', 'university_id', 'program_name', 'course_type',
                    'is_online', 'source_url', 'last_seen', 'quality_flag'],
                   varied_programs)
        self.saver.insert_programs_from_csv(str(prog_csv))

        cur = _stub_conn.connection.cursor()
        cur.execute("SELECT program_name, is_online FROM degree_programs ORDER BY id")
        rows = cur.fetchall()
        self.assertEqual(rows[0][1], 1, "is_online='true' は 1(True) に変換されるべき")
        self.assertEqual(rows[1][1], 0, "is_online='0' は 0(False) に変換されるべき")


if __name__ == '__main__':
    unittest.main(verbosity=2)
