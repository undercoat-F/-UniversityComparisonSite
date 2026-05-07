"""
候補サイトをsearchURLsに追加する前に取得可能かチェックするスクリプト。

使い方:
    python check_site.py
    → CANDIDATE_URLS リストに追加して実行

結果:
    OK       → BeautifulSoupで取得可能（searchURLsに追加してよい）
    BLOCKED  → Cloudflare等のBot保護で弾かれている
    JS_ONLY  → HTMLは返るがコンテンツがJS依存（SPA等）
    EMPTY    → HTML取得できたが本文が極端に少ない
"""

import httpx
import requests
import re

# ここに確認したいURLを追加する
CANDIDATE_URLS = [
    # 例:
    # "https://www.coursera.org/degrees",
    # "https://www.futurelearn.com/degrees",
]

KEYWORDS = ["bachelor", "master", "phd", "degree", "course", "programme", "tuition", "fee"]
CLOUDFLARE_SIGNS = ["just a moment", "enable javascript and cookies", "_cf_chl_opt"]
JS_SIGNS = ["<div id=\"app\"", "<div id=\"root\"", "__NEXT_DATA__", "window.__INITIAL_STATE__"]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

def check_url(url: str) -> tuple[str, str]:
    """(status, detail) を返す"""
    try:
        resp = httpx.get(url, headers=HEADERS, follow_redirects=True, timeout=20)
        # 403の場合はrequestsでフォールバック（クローラーと同じ挙動）
        if resp.status_code == 403:
            resp2 = requests.get(url, headers=HEADERS, timeout=20)
            html = resp2.text.lower()
            fetch_note = "requests(fallback)"
        else:
            html = resp.text.lower()
            fetch_note = "httpx"

        # Cloudflare Bot保護
        if any(sign in html for sign in CLOUDFLARE_SIGNS):
            return "BLOCKED", "Cloudflare Bot保護"

        # JS SPA
        if any(sign.lower() in html for sign in JS_SIGNS):
            return "JS_ONLY", "SPAフレームワーク検出"

        # 本文が短すぎる
        if len(html) < 2000:
            return "EMPTY", f"HTML {len(html)}文字 ({fetch_note})"

        # キーワードがあるか
        found = [kw for kw in KEYWORDS if kw in html]
        if found:
            return "OK", f"{fetch_note} / キーワード: {', '.join(found[:5])}"
        else:
            return "EMPTY", "キーワード未検出（構造確認が必要）"

    except httpx.TimeoutException:
        return "ERROR", "タイムアウト"
    except Exception as e:
        return "ERROR", str(e)


if __name__ == "__main__":
    if not CANDIDATE_URLS:
        print("CANDIDATE_URLS にURLを追加してから実行してください。")
        exit()

    print(f"{'URL':<60} {'結果':<10} 詳細")
    print("-" * 100)
    for url in CANDIDATE_URLS:
        status, detail = check_url(url)
        mark = "✅" if status == "OK" else "❌"
        print(f"{mark} {url:<58} [{status:<8}] {detail}")
