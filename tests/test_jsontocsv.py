#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
jsontocsv.py の簡易ユニットテスト
DB不要・ネット通信なし。一時ディレクトリでCSV生成を検証。
"""

import sys
import os
import json
import csv
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from db.jsontocsv import generate_csvs, normalize_degree_level, extract_university_name, extract_program_name

# ---------- テスト用JSONデータ ----------
SAMPLE_JSON = [
    {
        "url": "https://study.ed.ac.uk/programmes/pg/123-informatics",
        "title": "Informatics MSc - Postgraduate | The University of Edinburgh",
        "country": "UK",
        "timestamp": "2026-04-17T13:00:00+00:00",
        "degrees": [
            {"name": "Master", "price": 29400, "currency": "GBP",
             "course_type": "computer_science", "is_online": False,
             "limit": None, "context": "MSc tuition fee £29,400"},
        ],
        "raw_text": "Informatics MSc tuition fee £29,400",
        "source_type": "html",
    },
    {
        "url": "https://study.ed.ac.uk/programmes/pg/456-history",
        "title": "History MA - Postgraduate | The University of Edinburgh",
        "country": "UK",
        "timestamp": "2026-04-17T14:00:00+00:00",
        "degrees": [
            # 同じ料金パターン → tuition_patterns は重複しないはず
            {"name": "Master", "price": 29400, "currency": "GBP",
             "course_type": "humanities", "is_online": False,
             "limit": None, "context": "MA tuition fee £29,400"},
        ],
        "raw_text": "History MA tuition fee £29,400",
        "source_type": "html",
    },
    {
        "url": "https://study.ed.ac.uk/programmes/pg/789-physics",
        "title": "Physics PhD - Postgraduate | The University of Edinburgh",
        "country": "UK",
        "timestamp": "2026-04-17T15:00:00+00:00",
        "degrees": [
            {"name": "PhD", "price": 5000, "currency": "GBP",
             "course_type": "science", "is_online": False,
             "limit": None, "context": "PhD tuition fee £5,000"},
        ],
        "raw_text": "Physics PhD tuition fee £5,000",
        "source_type": "html",
    },
]


class TestNormalizeDegreeLevel(unittest.TestCase):

    def test_phd(self):
        self.assertEqual(normalize_degree_level("PhD"), "PhD")
        self.assertEqual(normalize_degree_level("doctorate"), "PhD")

    def test_master(self):
        self.assertEqual(normalize_degree_level("Master"), "Master")
        self.assertEqual(normalize_degree_level("MSc"), "Master")
        self.assertEqual(normalize_degree_level("Postgraduate"), "Master")

    def test_bachelor(self):
        self.assertEqual(normalize_degree_level("Bachelor"), "Bachelor")
        self.assertEqual(normalize_degree_level("undergraduate"), "Bachelor")

    def test_other(self):
        self.assertEqual(normalize_degree_level(""), "Other")
        self.assertEqual(normalize_degree_level(None), "Other")
        self.assertEqual(normalize_degree_level("certificate"), "Other")


class TestExtractHelpers(unittest.TestCase):

    def test_extract_university_name_edinburgh(self):
        name = extract_university_name("https://study.ed.ac.uk/programmes")
        self.assertEqual(name, "University of Edinburgh")

    def test_extract_university_name_fallback(self):
        name = extract_university_name("https://example.com/degrees")
        # フォールバックではドメイン主部が返る
        self.assertIn("example", name.lower())

    def test_extract_program_name_with_separator(self):
        title = "Informatics MSc - Postgraduate taught | The University of Edinburgh"
        self.assertEqual(extract_program_name(title), "Informatics MSc")

    def test_extract_program_name_without_separator(self):
        title = "Just a plain title"
        self.assertEqual(extract_program_name(title), "Just a plain title")


class TestGenerateCsvs(unittest.TestCase):

    def setUp(self):
        # 一時ディレクトリと一時JSONを作成
        self.tmpdir = tempfile.mkdtemp()
        self.json_path = os.path.join(self.tmpdir, "test.json")
        with open(self.json_path, 'w', encoding='utf-8') as f:
            json.dump(SAMPLE_JSON, f, ensure_ascii=False)

    def _read_csv(self, filename):
        path = Path(self.tmpdir) / filename
        with open(path, 'r', encoding='utf-8') as f:
            return list(csv.DictReader(f))

    def test_csv_files_are_created(self):
        generate_csvs(self.json_path, self.tmpdir)
        for name in ["universities.csv", "degree_programs.csv",
                     "tuition_patterns.csv", "program_tuition_map.csv"]:
            self.assertTrue((Path(self.tmpdir) / name).exists(), f"{name} が生成されるべき")

    def test_universities_count(self):
        generate_csvs(self.json_path, self.tmpdir)
        rows = self._read_csv("universities.csv")
        # 全て同じドメインなので 1 件
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "University of Edinburgh")

    def test_degree_programs_count(self):
        generate_csvs(self.json_path, self.tmpdir)
        rows = self._read_csv("degree_programs.csv")
        self.assertEqual(len(rows), 3, "degree_programs は JSON の degrees 数に対応")

    def test_tuition_patterns_deduplication(self):
        """同額パターン（Master/29400/GBP/tuition）は1件にまとまるべき"""
        generate_csvs(self.json_path, self.tmpdir)
        rows = self._read_csv("tuition_patterns.csv")
        # Master/29400, PhD/5000 → 2件
        self.assertEqual(len(rows), 2, f"重複排除後は2件のはず (実際: {len(rows)}件)")

    def test_program_tuition_map_count(self):
        generate_csvs(self.json_path, self.tmpdir)
        rows = self._read_csv("program_tuition_map.csv")
        # プログラム3件に対して各1件の対応
        self.assertEqual(len(rows), 3)

    def test_university_id_is_consistent(self):
        """degree_programs の university_id が universities.csv の id と一致するか"""
        generate_csvs(self.json_path, self.tmpdir)
        uni_ids = {row["id"] for row in self._read_csv("universities.csv")}
        prog_uni_ids = {row["university_id"] for row in self._read_csv("degree_programs.csv")}
        for uid in prog_uni_ids:
            self.assertIn(uid, uni_ids, f"university_id={uid} が universities.csv に存在しない")

    def test_map_ids_are_consistent(self):
        """program_tuition_map の FK が両テーブルに存在するか"""
        generate_csvs(self.json_path, self.tmpdir)
        prog_ids = {row["id"] for row in self._read_csv("degree_programs.csv")}
        pattern_ids = {row["id"] for row in self._read_csv("tuition_patterns.csv")}
        for row in self._read_csv("program_tuition_map.csv"):
            self.assertIn(row["degree_program_id"], prog_ids)
            self.assertIn(row["tuition_pattern_id"], pattern_ids)


if __name__ == '__main__':
    unittest.main(verbosity=2)
