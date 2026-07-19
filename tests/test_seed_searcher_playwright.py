#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Playwright fallback behavior tests for observer.seed_searcher.
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

from dataclass.dataclass import ContentType, PageAnalysis
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


class _DummyLocator:
    def __init__(self, count_value: int = 0):
        self._count_value = count_value
        self.clicked = False

    def count(self) -> int:
        return self._count_value

    @property
    def first(self):
        return self

    def click(self, timeout: int | None = None):
        self.clicked = True


class _DummyPageForPlaywright:
    def __init__(self, raw_items: list[dict[str, str]]):
        self.raw_items = raw_items
        self.goto_url = ""
        self.goto_wait_until = ""
        self.goto_timeout = 0
        self.wait_selector = ""
        self.wait_timeout = 0
        self.evaluated_script = ""
        self.fill_called = False

    def goto(self, url: str, wait_until: str, timeout: int):
        self.goto_url = url
        self.goto_wait_until = wait_until
        self.goto_timeout = timeout

    def locator(self, selector: str):
        return _DummyLocator(count_value=0)

    def wait_for_selector(self, selector: str, timeout: int):
        self.wait_selector = selector
        self.wait_timeout = timeout

    def evaluate(self, script: str):
        self.evaluated_script = script
        return self.raw_items

    def fill(self, selector: str, value: str):
        self.fill_called = True


class _DummyContextForPlaywright:
    def __init__(self, page: _DummyPageForPlaywright):
        self._page = page
        self.closed = False

    def new_page(self):
        return self._page

    def close(self):
        self.closed = True


class _DummyBrowserForPlaywright:
    def __init__(self, page: _DummyPageForPlaywright):
        self.page = page
        self.context = _DummyContextForPlaywright(page)
        self.closed = False

    def new_context(self, user_agent: str, locale: str):
        return self.context

    def close(self):
        self.closed = True


class _DummyChromiumForPlaywright:
    def __init__(self, page: _DummyPageForPlaywright):
        self.page = page

    def launch(self, headless: bool):
        return _DummyBrowserForPlaywright(self.page)


class _DummySyncPlaywrightCM:
    def __init__(self, page: _DummyPageForPlaywright):
        self.chromium = _DummyChromiumForPlaywright(page)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


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


class TestSeedSearcherPlaywright(unittest.TestCase):
    def test_playwright_search_uses_query_param_and_external_script(self):
        page = _DummyPageForPlaywright(
            raw_items=[
                {
                    "url": "https://www.example.ac.uk/programmes",
                    "title": "Programmes",
                    "snippet": "Find your programme",
                }
            ]
        )

        with (
            patch("observer.seed_searcher.sync_playwright", return_value=_DummySyncPlaywrightCM(page)),
            patch.dict("os.environ", {"PLAYWRIGHT_GOOGLE_FALLBACK": "1"}, clear=False),
        ):
            client = seed_searcher.PlaywrightFallbackSearch()
            rows = client.search(query="Tokyo University", num_results=5)

        self.assertIn("https://www.google.com/search", page.goto_url)
        self.assertIn("q=Tokyo+University", page.goto_url)
        self.assertEqual(page.goto_wait_until, "domcontentloaded")
        self.assertEqual(page.wait_selector, "div#search")
        self.assertEqual(page.evaluated_script, seed_searcher.GOOGLE_RESULTS_EXTRACT_SCRIPT)
        self.assertFalse(page.fill_called)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["url"], "https://www.example.ac.uk/programmes")

    def test_provider_fallback_uses_playwright_when_brave_key_missing(self):
        item = _build_item("Playwright University")

        def fake_playwright_search(query: str, num_results: int = 10):
            if query in {"Playwright University 公式", "Playwright University official"}:
                return [
                    {
                        "url": "https://www.playwright.ac.uk/programmes",
                        "title": "Programmes",
                        "snippet": "Find your programme",
                    }
                ]
            return []

        with (
            patch.dict("os.environ", {"BRAVE_API_KEY": "", "PLAYWRIGHT_GOOGLE_FALLBACK": "1"}, clear=False),
            patch("observer.seed_searcher.PlaywrightFallbackSearch.search", side_effect=fake_playwright_search),
            patch("observer.seed_searcher._existing_root_urls", return_value=set()),
            patch("observer.seed_searcher.SearchLogStore.from_env", return_value=None),
            patch("observer.seed_searcher._probe_hits_async", new=_passthrough_probe_hits),
            patch(
                "observer.seed_searcher.requests.get",
                return_value=_DummyResponse(text="<html><body>ok</body></html>"),
            ),
        ):
            result = seed_searcher.search_seeds(item)

        self.assertEqual(result.api_type, "playwright-google")
        self.assertTrue(result.fallback_executed)
        self.assertTrue(any("playwright.ac.uk" in u for u in result.root_seed_urls))

    def test_provider_fallback_returns_error_when_both_brave_and_playwright_fail(self):
        item = _build_item("Fail University")

        def fail_brave(query: str, num_results: int = 10):
            raise RuntimeError("brave quota exceeded")

        def fail_playwright(query: str, num_results: int = 10):
            raise RuntimeError("playwright blocked")

        with (
            patch.dict("os.environ", {"BRAVE_API_KEY": "dummy-key", "PLAYWRIGHT_GOOGLE_FALLBACK": "1"}, clear=False),
            patch("observer.seed_searcher.BraveSearchAPI.search", side_effect=fail_brave),
            patch("observer.seed_searcher.PlaywrightFallbackSearch.search", side_effect=fail_playwright),
            patch("observer.seed_searcher._existing_root_urls", return_value=set()),
            patch("observer.seed_searcher.SearchLogStore.from_env", return_value=None),
        ):
            result = seed_searcher.search_seeds(item)

        self.assertFalse(result.hits)
        self.assertTrue(any("all_search_providers_failed" in err for err in result.errors))
        self.assertTrue(any("search_failed:" in err for err in result.errors))


if __name__ == "__main__":
    unittest.main(verbosity=2)
