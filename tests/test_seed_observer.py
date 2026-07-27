#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Unit tests for observer.seed_observer.extract_universitynamelist.
"""

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from dataclass.dataclass import ContentType, PageAnalysis
from observer.seed_observer import (
    extract_candidate_lines,
    extract_universitynamelist,
    extract_pagination_actions,
    observe_url,
)


def make_page(candidate_lines: list[str]) -> PageAnalysis:
    page = PageAnalysis()
    page.content_type = ContentType.HTML
    page.candidate_lines = candidate_lines
    return page


class _DummyResponse:
    def __init__(self, text: str) -> None:
        self.text = text
        self.content = text.encode("utf-8")
        self.status_code = 200
        self.url = "https://example.org"
        self.headers = {"Content-Type": "text/html; charset=utf-8"}


class _FakeSession:
    def __init__(self, initial_html: str, next_html: str) -> None:
        self.initial_html = initial_html
        self.next_html = next_html
        self.headers = {}

    def get(self, url, headers=None, timeout=None, allow_redirects=True):
        resp = _DummyResponse(self.initial_html)
        resp.url = url
        return resp

    def post(self, url, data=None, headers=None, timeout=None, allow_redirects=True):
        resp = _DummyResponse(self.next_html)
        resp.url = url
        return resp


def make_html_page(html: str) -> PageAnalysis:
    page = PageAnalysis()
    page.content_type = ContentType.HTML
    page.response = _DummyResponse(html)
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


class TestExtractCandidateLinesHTML(unittest.TestCase):
        def test_extracts_from_td_and_a_tags(self):
                page = make_html_page(
                        """
                        <html><body>
                            <table>
                                <tbody>
                                    <tr><td><a href='/uni/tokyo'>東京大学</a></td><td>国立</td></tr>
                                    <tr><td><a href='/uni/kyoto'>京都大学</a></td><td>国立</td></tr>
                                </tbody>
                            </table>
                        </body></html>
                        """
                )

                lines = extract_candidate_lines(page)

                self.assertTrue(any("東京大学" in line for line in lines))
                self.assertTrue(any("京都大学" in line for line in lines))

        def test_extracts_from_li_and_option_tags(self):
                page = make_html_page(
                        """
                        <html><body>
                            <ul>
                                <li><a href='/uni/waseda'>早稲田大学</a></li>
                                <li><a href='/uni/keio'>慶應義塾大学</a></li>
                            </ul>
                            <select>
                                <option value='utokyo'>東京大学</option>
                                <option value='kyoto'>京都大学</option>
                            </select>
                        </body></html>
                        """
                )

                lines = extract_candidate_lines(page)

                self.assertTrue(any("早稲田大学" in line for line in lines))
                self.assertTrue(any("慶應義塾大学" in line for line in lines))
                self.assertTrue(any("東京大学" in line for line in lines))
                self.assertTrue(any("京都大学" in line for line in lines))

        def test_extracts_h3_inside_div_cards(self):
                page = make_html_page(
                        """
                        <html><body>
                            <div class='result-card'>
                                <h3>北海道医療大学</h3>
                                <p>医療系大学</p>
                            </div>
                            <div class='result-card'>
                                <h3>日本女子大学</h3>
                                <p>私立大学</p>
                            </div>
                        </body></html>
                        """
                )

                lines = extract_candidate_lines(page)

                self.assertTrue(any("北海道医療大学" in line for line in lines))
                self.assertTrue(any("日本女子大学" in line for line in lines))

        def test_extracts_from_anchor_title_when_text_empty(self):
            page = make_html_page(
                """
                <html><body>
                    <a href='/provider/1' title='Australian Catholic University'></a>
                    <a href='/provider/2' aria-label='Monash University'></a>
                </body></html>
                """
             )

            lines = extract_candidate_lines(page)

            self.assertTrue(any("Australian Catholic University" in line for line in lines))
            self.assertTrue(any("Monash University" in line for line in lines))


class TestPaginationExtractionAndObserve(unittest.TestCase):
        def test_extract_pagination_actions_from_button_postback(self):
                html = """
                <html><body>
                    <button onclick="javascript:__doPostBack('ctl00$Main$EducationDirectory$pager','2')">次へ</button>
                </body></html>
                """

                actions = extract_pagination_actions(html, "https://example.org/results")

                self.assertTrue(any(action["method"] == "postback" for action in actions))
                self.assertTrue(any(action["argument"] == "2" for action in actions))

        def test_observe_url_collects_followup_page_candidates(self):
                initial_html = """
                <html><body>
                    <table>
                        <tbody>
                            <tr><td><a href='/school/page1'>AAA College</a></td></tr>
                        </tbody>
                    </table>
                    <button onclick="javascript:__doPostBack('ctl00$Main$EducationDirectory$pager','2')">次へ</button>
                </body></html>
                """
                next_html = """
                <html><body>
                    <table>
                        <tbody>
                            <tr><td><a href='/school/page2'>BBB College</a></td></tr>
                        </tbody>
                    </table>
                </body></html>
                """

                def fake_get(url, headers=None, timeout=None, allow_redirects=True):
                        if url.endswith("/robots.txt"):
                                resp = _DummyResponse("")
                                resp.status_code = 200
                                resp.text = ""
                                return resp
                        resp = _DummyResponse(initial_html)
                        resp.url = url
                        return resp

                with (
                        patch("observer.seed_observer.get_crawl_delay", return_value=0.0),
                        patch("observer.seed_observer.time.sleep", return_value=None),
                        patch("observer.seed_observer.requests.get", side_effect=fake_get),
                        patch("observer.seed_observer.requests.Session", return_value=_FakeSession(initial_html, next_html)),
                ):
                        page = observe_url("https://example.org/results")

                self.assertIsNotNone(page)
                self.assertTrue(any("AAA College" in line for line in page.candidate_lines))
                self.assertTrue(any("BBB College" in line for line in page.candidate_lines))
                self.assertTrue(any("AAA College" in name for name in page.extracted_universitynamelist))
                self.assertTrue(any("BBB College" in name for name in page.extracted_universitynamelist))


if __name__ == "__main__":
    unittest.main(verbosity=2)
