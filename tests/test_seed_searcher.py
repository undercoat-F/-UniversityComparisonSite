#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
test_seed_searcher.py
seed_searcher のユニットテスト
- 検索API呼び出し
- 公式ページからの内部リンク抽出
- コース未検出時の fallback 再検索
ネット通信なし・DB不要。
"""

import os
import sys
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

if "psycopg2" not in sys.modules:
    sys.modules["psycopg2"] = types.SimpleNamespace(Error=Exception)
if "dotenv" not in sys.modules:
    sys.modules["dotenv"] = types.SimpleNamespace(load_dotenv=lambda *a, **k: None)

from dataclass.dataclass import ContentType, PageAnalysis, SearchHit
from observer.observe_supervisor import ObserveStackItem
from observer import seed_searcher


class _DummyResponse:
    def __init__(self, text: str, content_type: str = "text/html", status_code: int = 200):
        self.text = text
        self.status_code = status_code
        self.headers = {"content-type": content_type}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _build_item(university_name: str = "Test University") -> ObserveStackItem:
    page = PageAnalysis(content_type=ContentType.HTML)
    page.extracted_universitynamelist = [university_name]
    return ObserveStackItem(
        source_url="https://observer.example.org/list",
        page_analysis=page,
        university_names=[university_name],
        request_logs=[],
    )


async def _passthrough_probe_hits(hits, errors):
    return hits


class TestSeedSearcher(unittest.TestCase):
    def test_sitemap_discovery_adds_course_candidates(self):
        item = _build_item("Sitemap University")

        def fake_search(query: str, num_results: int = 10):
            if query == "Sitemap University":
                return [
                    {
                        "url": "https://www.sitemap.ac.uk/",
                        "title": "Sitemap University Official Site",
                        "snippet": "Official",
                    }
                ]
            return []

        def fake_requests_get(url, headers=None, timeout=None, allow_redirects=True):
            if url == "https://www.sitemap.ac.uk/robots.txt":
                return _DummyResponse("Sitemap: https://www.sitemap.ac.uk/sitemap.xml", content_type="text/plain")
            if url == "https://www.sitemap.ac.uk/sitemap.xml":
                return _DummyResponse(
                    """
                    <urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">
                      <url><loc>https://www.sitemap.ac.uk/courses/undergraduate</loc></url>
                      <url><loc>https://www.sitemap.ac.uk/programmes/postgraduate</loc></url>
                    </urlset>
                    """,
                    content_type="application/xml",
                )
            return _DummyResponse("<html><body>ok</body></html>")

        with (
            patch.dict("os.environ", {"BRAVE_API_KEY": "dummy-key"}, clear=False),
            patch("observer.seed_searcher.BraveSearchAPI.search", side_effect=fake_search),
            patch("observer.seed_searcher._existing_root_urls", return_value=set()),
            patch("observer.seed_searcher.SearchLogStore.from_env", return_value=None),
            patch("observer.seed_searcher._probe_hits_async", new=_passthrough_probe_hits),
            patch("observer.seed_searcher.requests.get", side_effect=fake_requests_get),
        ):
            result = seed_searcher.search_seeds(item)

        self.assertTrue(any("/courses/undergraduate" in url for url in result.detailed_seed_urls))
        self.assertTrue(any(hit.query == "sitemap" for hit in result.hits))

    def test_search_and_internal_link_exploration(self):
        item = _build_item("Test University")

        def fake_search(query: str, num_results: int = 10):
            if query == "Test University":
                return [
                    {
                        "url": "https://www.testuniversity.ac.uk/",
                        "title": "Test University Official Site",
                        "snippet": "Welcome",
                    }
                ]
            return []

        async def fake_probe_urls_async(urls, errors):
            # 内部リンク探索で見つかった URL を course-like として返す
            return [
                SearchHit(
                    query="internal-link",
                    url="https://www.testuniversity.ac.uk/courses",
                    title="Courses",
                    snippet="Undergraduate and postgraduate courses",
                    score=10.0,
                    is_course_like=True,
                    course_list_detected=True,
                )
            ]

        with (
            patch.dict("os.environ", {"BRAVE_API_KEY": "dummy-key"}, clear=False),
            patch("observer.seed_searcher.BraveSearchAPI.search", side_effect=fake_search) as m_search,
            patch("observer.seed_searcher._existing_root_urls", return_value=set()),
            patch("observer.seed_searcher.SearchLogStore.from_env", return_value=None),
            patch("observer.seed_searcher._probe_hits_async", new=_passthrough_probe_hits),
            patch("observer.seed_searcher._probe_urls_async", new=fake_probe_urls_async),
            patch(
                "observer.seed_searcher.requests.get",
                return_value=_DummyResponse(
                    text='<html><body><a href="/courses">Courses</a></body></html>'
                ),
            ),
        ):
            result = seed_searcher.search_seeds(item)

        self.assertGreaterEqual(m_search.call_count, 2)  # 第1検索は大学名 + official site
        self.assertTrue(result.course_list_found)
        self.assertEqual(result.recommended_depth, 1)
        self.assertTrue(any("/courses" in url for url in result.detailed_seed_urls))

    def test_fallback_search_runs_when_course_not_found(self):
        item = _build_item("Fallback University")

        call_queries = []

        def fake_search(query: str, num_results: int = 10):
            call_queries.append(query)
            if query == "Fallback University":
                return [
                    {
                        "url": "https://www.fallback.ac.uk/",
                        "title": "Fallback University Official Site",
                        "snippet": "Welcome",
                    }
                ]
            if query == "Fallback University official site":
                return []
            if query == "site:www.fallback.ac.uk courses":
                return []
            if query == "site:www.fallback.ac.uk programmes":
                return [
                    {
                        "url": "https://www.fallback.ac.uk/programmes",
                        "title": "Programmes",
                        "snippet": "Find your programme",
                    }
                ]
            return []

        with (
            patch.dict("os.environ", {"BRAVE_API_KEY": "dummy-key"}, clear=False),
            patch("observer.seed_searcher.BraveSearchAPI.search", side_effect=fake_search) as m_search,
            patch("observer.seed_searcher._existing_root_urls", return_value=set()),
            patch("observer.seed_searcher.SearchLogStore.from_env", return_value=None),
            patch("observer.seed_searcher._probe_hits_async", new=_passthrough_probe_hits),
            patch(
                "observer.seed_searcher.requests.get",
                return_value=_DummyResponse(text="<html><body><a href='/about'>About</a></body></html>"),
            ),
        ):
            result = seed_searcher.search_seeds(item)

        # fallback クエリまで呼ばれていることを確認
        self.assertGreaterEqual(m_search.call_count, 4)
        self.assertIn("site:www.fallback.ac.uk courses", call_queries)
        self.assertIn("site:www.fallback.ac.uk programmes", call_queries)
        self.assertTrue(result.course_list_found)
        self.assertEqual(result.recommended_depth, 1)
        self.assertTrue(any("/programmes" in hit.url for hit in result.hits))


if __name__ == "__main__":
    unittest.main(verbosity=2)
