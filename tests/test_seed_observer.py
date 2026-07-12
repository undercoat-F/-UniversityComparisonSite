#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Unit tests for observer.seed_observer.extract_universitynamelist.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from dataclass.dataclass import ContentType, PageAnalysis
from observer.seed_observer import extract_universitynamelist


def make_page(candidate_lines: list[str]) -> PageAnalysis:
    page = PageAnalysis()
    page.content_type = ContentType.HTML
    page.candidate_lines = candidate_lines
    return page


class TestExtractUniversityNamelistJapanese(unittest.TestCase):
    def test_basic_daigaku(self):
        page = make_page(["東京大学 入試情報"])
        result = extract_universitynamelist(page)
        self.assertIn("東京大学", result)

    def test_noise_stripped_from_jp(self):
        page = make_page(["東京大学 教育学部"])
        result = extract_universitynamelist(page)
        self.assertIn("東京大学", result)
        self.assertFalse(any("教育学部" in r for r in result))

    def test_multiple_jp_universities(self):
        page = make_page([
            "大阪公立大学 | 偏差値・学費一覧",
            "慶應義塾大学 募集要項",
        ])
        result = extract_universitynamelist(page)
        self.assertIn("大阪公立大学", result)
        self.assertIn("慶應義塾大学", result)

    def test_daigakuin(self):
        page = make_page(["東京大学大学院 工学系研究科"])
        result = extract_universitynamelist(page)
        self.assertTrue(any("大学院" in r for r in result))

    def test_jp_noise_only_not_extracted(self):
        page = make_page(["入試情報 募集要項 一覧"])
        result = extract_universitynamelist(page)
        self.assertEqual(result, [])


class TestExtractUniversityNamelistEnglish(unittest.TestCase):
    def test_basic_university(self):
        page = make_page(["The University of Tokyo | Admissions"])
        result = extract_universitynamelist(page)
        self.assertTrue(any("University of Tokyo" in r for r in result))

    def test_admissions_noise_stripped(self):
        page = make_page(["University College London Admissions 2024"])
        result = extract_universitynamelist(page)
        self.assertFalse(any("Admissions" in r for r in result))

    def test_courses_noise_stripped(self):
        page = make_page(["Kyoto University / Courses"])
        result = extract_universitynamelist(page)
        self.assertTrue(any("Kyoto University" in r for r in result))
        self.assertFalse(any("Courses" in r for r in result))

    def test_multiple_en_universities(self):
        page = make_page([
            "Oxford University | Apply",
            "University of Manchester - Entry Requirements",
        ])
        result = extract_universitynamelist(page)
        self.assertTrue(any("Oxford University" in r for r in result))
        self.assertTrue(any("University of Manchester" in r for r in result))

    def test_separator_split(self):
        page = make_page(["King's College London | Imperial College London"])
        result = extract_universitynamelist(page)
        self.assertTrue(any("King" in r and "College" in r for r in result))
        self.assertTrue(any("Imperial College" in r for r in result))

    def test_en_noise_only_not_extracted(self):
        page = make_page(["Admissions Apply Fees Tuition"])
        result = extract_universitynamelist(page)
        self.assertEqual(result, [])


class TestExtractUniversityNamelistMixed(unittest.TestCase):
    def test_mixed_line(self):
        page = make_page([
            "東京大学 | The University of Tokyo",
            "京都大学 / Kyoto University",
        ])
        result = extract_universitynamelist(page)
        self.assertIn("東京大学", result)
        self.assertIn("京都大学", result)
        self.assertTrue(any("University of Tokyo" in r for r in result))
        self.assertTrue(any("Kyoto University" in r for r in result))

    def test_no_duplicates(self):
        page = make_page(["東京大学", "東京大学"])
        result = extract_universitynamelist(page)
        self.assertEqual(result.count("東京大学"), 1)

    def test_result_stored_on_page(self):
        page = make_page(["早稲田大学"])
        result = extract_universitynamelist(page)
        self.assertEqual(result, page.extracted_universitynamelist)


if __name__ == "__main__":
    unittest.main(verbosity=2)
