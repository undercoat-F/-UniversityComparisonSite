#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
test_site_profile.py
URL分類ロジックのユニットテスト
- should_exclude_course_page(): ノイズページの除外判定
- is_url_in_scope(): クロールスコープ制限
- is_non_html_url(): 非HTMLファイルの判定
ネット通信なし・DB不要。
"""

import sys
import os
import unittest
import builtins

# crawlAndSaver import 時の input() を無害化
_real_input = builtins.input
builtins.input = lambda *a, **kw: "https://example.com"

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from crawler.crawlAndSaver import should_exclude_course_page, is_url_in_scope, is_non_html_url

builtins.input = _real_input


class TestShouldExcludeCoursePage(unittest.TestCase):
    """should_exclude_course_page: ノイズページを除外できるか"""

    def test_scholarship_url_is_excluded(self):
        self.assertTrue(
            should_exclude_course_page("https://ed.ac.uk/scholarships", "Scholarships")
        )

    def test_funding_title_is_excluded(self):
        self.assertTrue(
            should_exclude_course_page("https://ed.ac.uk/pg/finance", "Funding your studies")
        )

    def test_alumni_is_excluded(self):
        self.assertTrue(
            should_exclude_course_page("https://ed.ac.uk/alumni/network", "Alumni Network")
        )

    def test_graduation_is_excluded(self):
        self.assertTrue(
            should_exclude_course_page("https://ed.ac.uk/graduation-ceremony", "Graduation")
        )

    def test_how_to_apply_is_excluded(self):
        self.assertTrue(
            should_exclude_course_page("https://ed.ac.uk/how-apply", "How to Apply")
        )

    def test_normal_course_page_is_not_excluded(self):
        self.assertFalse(
            should_exclude_course_page(
                "https://study.ed.ac.uk/programmes/postgraduate/informatics-msc",
                "Informatics MSc | The University of Edinburgh"
            )
        )

    def test_phd_programme_is_not_excluded(self):
        self.assertFalse(
            should_exclude_course_page(
                "https://study.ed.ac.uk/programmes/postgraduate-research/physics-phd",
                "Physics PhD Programme"
            )
        )

    def test_student_services_is_excluded(self):
        self.assertTrue(
            should_exclude_course_page("https://ed.ac.uk/student-services/help", "Student Services")
        )

    def test_taster_courses_is_excluded(self):
        self.assertTrue(
            should_exclude_course_page("https://ed.ac.uk/taster-courses", "Taster Courses")
        )


class TestIsUrlInScope(unittest.TestCase):
    """is_url_in_scope: クロールスコープ制限が正しく動くか"""

    def test_same_path_prefix_is_in_scope(self):
        self.assertTrue(
            is_url_in_scope(
                "https://study.ed.ac.uk/programmes/postgraduate/informatics",
                "https://study.ed.ac.uk/programmes/postgraduate"
            )
        )

    def test_exact_match_is_in_scope(self):
        self.assertTrue(
            is_url_in_scope(
                "https://study.ed.ac.uk/programmes/postgraduate",
                "https://study.ed.ac.uk/programmes/postgraduate"
            )
        )

    def test_different_path_is_out_of_scope(self):
        self.assertFalse(
            is_url_in_scope(
                "https://study.ed.ac.uk/about/university",
                "https://study.ed.ac.uk/programmes/postgraduate"
            )
        )

    def test_different_domain_is_out_of_scope(self):
        self.assertFalse(
            is_url_in_scope(
                "https://www.london.ac.uk/courses",
                "https://study.ed.ac.uk/programmes/postgraduate"
            )
        )

    def test_partial_path_match_is_out_of_scope(self):
        # /programmes/postgraduate-research は
        # /programmes/postgraduate のスコープ外であるべき
        self.assertFalse(
            is_url_in_scope(
                "https://study.ed.ac.uk/programmes/postgraduate-research/123",
                "https://study.ed.ac.uk/programmes/postgraduate"
            )
        )

    def test_london_ug_scope(self):
        self.assertTrue(
            is_url_in_scope(
                "https://www.london.ac.uk/study/courses/undergraduate/bsc-economics",
                "https://www.london.ac.uk/study/courses/undergraduate"
            )
        )


class TestIsNonHtmlUrl(unittest.TestCase):
    """is_non_html_url: PDF・画像などの非HTMLファイルを除外できるか"""

    def test_pdf_is_non_html(self):
        self.assertTrue(is_non_html_url("https://ed.ac.uk/prospectus.pdf"))

    def test_jpg_is_non_html(self):
        self.assertTrue(is_non_html_url("https://ed.ac.uk/campus.jpg"))

    def test_docx_is_non_html(self):
        self.assertTrue(is_non_html_url("https://ed.ac.uk/application-form.docx"))

    def test_zip_is_non_html(self):
        self.assertTrue(is_non_html_url("https://ed.ac.uk/resources.zip"))

    def test_html_page_is_not_non_html(self):
        self.assertFalse(
            is_non_html_url("https://study.ed.ac.uk/programmes/postgraduate/informatics")
        )

    def test_query_param_page_is_not_non_html(self):
        self.assertFalse(
            is_non_html_url("https://ed.ac.uk/search?q=master")
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
