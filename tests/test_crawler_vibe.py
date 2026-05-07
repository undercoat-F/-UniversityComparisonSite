#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
クローラー（crawlAndSaver.py）の簡易ユニットテスト
ネット通信なし・DB不要。ロジック部分のみをテスト。
"""

import sys
import os
import unittest

# crawlAndSaver を import するために crawler/ をパスに追加
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'crawler'))

# crawlAndSaver は実行時に input() を呼ぶため、ここで差し替えておく
import builtins
_real_input = builtins.input
builtins.input = lambda *a, **kw: "https://example.com"

from crawler.crawlAndSaver import crawlAndSaver as caw

builtins.input = _real_input  # 復元


class TestDetectCourseType(unittest.TestCase):

    def test_computer_science(self):
        result = caw.detect_course_type("Master of Computer Science and Machine Learning")
        self.assertEqual(result, "computer_science")

    def test_engineering(self):
        result = caw.detect_course_type("MEng Civil Engineering programme")
        self.assertEqual(result, "engineering")

    def test_business(self):
        result = caw.detect_course_type("MBA in Business Management")
        self.assertEqual(result, "business")

    def test_health(self):
        result = caw.detect_course_type("Bachelor of Medicine and Clinical Practice")
        self.assertEqual(result, "health")

    def test_law(self):
        result = caw.detect_course_type("LLM in International Law")
        self.assertEqual(result, "law")

    def test_no_keywords_returns_general(self):
        result = caw.detect_course_type("Some random page with no relevant words")
        self.assertEqual(result, "general")


class TestExtractInfo(unittest.TestCase):
    """extract_info: テキストから学位・料金を抽出できるか"""

    def test_extracts_master_gbp(self):
        text = (
            "Postgraduate tuition fees for master programmes.\n"
            "Master degree tuition fee: £5,000 per year.\n"
        )
        degrees = caw.extract_info(text, "Masters Fees | University")
        self.assertTrue(len(degrees) > 0, "学位レコードが1件以上抽出されるべき")
        prices = [d["price"] for d in degrees]
        self.assertIn(5000, prices)
        currencies = [d["currency"] for d in degrees]
        self.assertTrue(any(c in ("GBP", "£") for c in currencies))

    def test_excludes_no_price(self):
        text = "This is a master degree programme. No fee information here.\n"
        degrees = caw.extract_info(text, "")
        self.assertEqual(degrees, [], "price が None のレコードは除外されるべき")

    def test_excludes_no_currency(self):
        text = "Master tuition fee 5000 per year.\n"
        degrees = caw.extract_info(text, "")
        # currency なしは除外
        for d in degrees:
            self.assertIsNotNone(d["currency"], "currency=None は除外されるべき")

    def test_online_flag(self):
        text = "PhD online tuition fees: £3,000 per year.\n"
        degrees = caw.extract_info(text, "")
        online_degrees = [d for d in degrees if d["is_online"]]
        self.assertTrue(len(online_degrees) > 0, "online キーワードで is_online=True になるべき")


class TestDeduplication(unittest.TestCase):
    """dedupe_degrees / dedupe_records の重複除去ロジック"""

    def test_dedupe_degrees_removes_exact_duplicate(self):
        degree = {
            "name": "Master",
            "price": 5000,
            "currency": "GBP",
            "course_type": "humanities",
            "is_online": False,
            "limit": None,
            "context": "master degree tuition fee £5,000",
        }
        duplicated = [degree, degree.copy()]
        result = caw.dedupe_degrees(duplicated)
        self.assertEqual(len(result), 1)

    def test_dedupe_degrees_keeps_different(self):
        d1 = {"name": "Master", "price": 5000, "currency": "GBP",
              "course_type": "humanities", "is_online": False, "limit": None, "context": "a"}
        d2 = {"name": "PhD", "price": 8000, "currency": "GBP",
              "course_type": "science", "is_online": False, "limit": None, "context": "b"}
        result = caw.dedupe_degrees([d1, d2])
        self.assertEqual(len(result), 2)

    def test_dedupe_records_merges_same_url(self):
        record = {
            "url": "https://example.com/fees",
            "title": "Fees Page",
            "country": "UK",
            "timestamp": "2026-01-01T00:00:00+00:00",
            "degrees": [
                {"name": "Master", "price": 5000, "currency": "GBP",
                 "course_type": "humanities", "is_online": False, "limit": None, "context": "master fee £5,000"},
            ],
            "raw_text": "master fee £5,000",
            "source_type": "html",
        }
        records = [record, record.copy()]
        result = caw.dedupe_records(records)
        self.assertEqual(len(result), 1, "同一URL・タイトルは1件にマージされるべき")


class TestGuessCountry(unittest.TestCase):

    def test_uk(self):
        self.assertEqual(caw.guess_country_from_url("https://study.ed.ac.uk/programmes"), "UK")

    def test_us(self):
        self.assertEqual(caw.guess_country_from_url("https://mit.edu/graduate"), "US")

    def test_jp(self):
        self.assertEqual(caw.guess_country_from_url("https://www.u-tokyo.ac.jp/programs"), "JP")

    def test_unknown(self):
        self.assertEqual(caw.guess_country_from_url("https://example.com/fees"), "unknown")


if __name__ == '__main__':
    unittest.main(verbosity=2)
