from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import quote_plus

from playwright.sync_api import sync_playwright


DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}

GOOGLE_RESULTS_EXTRACT_SCRIPT = (
    Path(__file__).with_name("google_extract_results.js").read_text(encoding="utf-8")
)


CONSENT_SELECTORS = (
    'button:has-text("I agree")',
    'button:has-text("Accept all")',
    'button:has-text("同意する")',
    'button:has-text("すべて受け入れる")',
)


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Debug Google fallback search with Playwright")
    parser.add_argument("query", help="Search query to send to Google")
    parser.add_argument("--num", type=int, default=8, help="Requested result count")
    parser.add_argument(
        "--output-dir",
        default=str(Path("log") / "playwright_debug"),
        help="Directory to save HTML, screenshot, and extracted JSON",
    )
    parser.add_argument(
        "--show-browser",
        action="store_true",
        help="Launch browser in headed mode for visual debugging",
    )
    return parser


def main() -> None:
    args = _build_arg_parser().parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    google_url = (
        "https://www.google.com/search"
        f"?q={quote_plus(args.query)}&num={max(1, min(int(args.num), 10))}&hl=en"
    )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=not args.show_browser)
        context = browser.new_context(
            user_agent=DEFAULT_HEADERS["User-Agent"],
            locale="en-US",
        )
        page = context.new_page()

        print(f"[DEBUG] goto={google_url}")
        page.goto(google_url, wait_until="domcontentloaded", timeout=20000)
        print(f"[DEBUG] landing_url={page.url}")

        clicked_selector = None
        for selector in CONSENT_SELECTORS:
            try:
                count = page.locator(selector).count()
                print(f"[DEBUG] consent_selector={selector} count={count}")
                if count > 0:
                    page.locator(selector).first.click(timeout=800)
                    clicked_selector = selector
                    break
            except Exception as exc:  # noqa: BLE001
                print(f"[DEBUG] consent_selector_error={selector} error={type(exc).__name__}: {exc}")

        if clicked_selector is not None:
            print(f"[DEBUG] consent_clicked={clicked_selector}")

        try:
            page.wait_for_selector("div#search", timeout=5000)
            print("[DEBUG] search_container_found=true")
        except Exception as exc:  # noqa: BLE001
            print(f"[DEBUG] search_container_found=false error={type(exc).__name__}: {exc}")

        title = page.title()
        print(f"[DEBUG] page_title={title}")

        raw_items = page.evaluate(GOOGLE_RESULTS_EXTRACT_SCRIPT)
        print(f"[DEBUG] extracted_count={len(raw_items or [])}")

        html_path = output_dir / "google_debug.html"
        screenshot_path = output_dir / "google_debug.png"
        json_path = output_dir / "google_debug_results.json"

        html_path.write_text(page.content(), encoding="utf-8")
        page.screenshot(path=str(screenshot_path), full_page=True)
        json_path.write_text(json.dumps(raw_items or [], ensure_ascii=False, indent=2), encoding="utf-8")

        print(f"[DEBUG] html_saved={html_path}")
        print(f"[DEBUG] screenshot_saved={screenshot_path}")
        print(f"[DEBUG] results_saved={json_path}")

        if raw_items:
            for index, item in enumerate(raw_items[:5], start=1):
                print(
                    f"[DEBUG] result_{index}="
                    f"{item.get('title', '')} | {item.get('url', '')}"
                )

        context.close()
        browser.close()


if __name__ == "__main__":
    main()