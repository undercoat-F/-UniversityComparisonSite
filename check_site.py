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


    # --- UK ---
    "https://www.manchester.ac.uk/study/undergraduate/courses/", 
    "https://www.manchester.ac.uk/study/masters/courses/list/",
     "https://www.birmingham.ac.uk/study/undergraduate/courses",
     "https://www.birmingham.ac.uk/study/postgraduate/taught/courses",
     "https://www.bristol.ac.uk/study/undergraduate/courses/",
     "https://www.bristol.ac.uk/study/postgraduate/taught/courses/",
     "https://www.leeds.ac.uk/undergraduate-courses",
     "https://courses.leeds.ac.uk/",
     "https://www.southampton.ac.uk/courses/undergraduate",
     "https://www.southampton.ac.uk/courses/postgraduate-taught",
     "https://www.york.ac.uk/study/undergraduate/courses/",
     "https://www.york.ac.uk/study/postgraduate-taught/courses/",
     "https://www.exeter.ac.uk/study/undergraduate/courses/",
     "https://www.exeter.ac.uk/study/postgraduate/courses/",
     "https://www.sheffield.ac.uk/undergraduate/courses",
     "https://www.sheffield.ac.uk/postgraduate/taught/courses",

    # --- Ireland ---
     "https://www.ucd.ie/courses/",
     "https://www.tcd.ie/courses/",   # JSサイト確認済み　Cloudflare Bot保護確認済み、不可
     "https://www.universityofgalway.ie/courses/",
     "https://www.ucc.ie/en/study/courses/",
     "https://www.universityofgalway.ie/courses/",
    "https://www.ucc.ie/en/study/courses/",

    # --- Australia ---
     "https://www.sydney.edu.au/courses/",
    "https://study.unimelb.edu.au/find", 
    "https://www.unsw.edu.au/study",
    "https://www.monash.edu/study/courses",
    "https://www.uq.edu.au/study/options",
    "https://www.adelaide.edu.au/degree-finder/",
    "https://www.anu.edu.au/study",
    "https://www.deakin.edu.au/course",
    "https://www.cdu.edu.au/study",
    "https://www.latrobe.edu.au/courses",
    "https://www.murdoch.edu.au/study",
    "https://www.utas.edu.au/courses", 
    "https://www.vu.edu.au/study-at-vu/courses",

    # --- New Zealand ---
    "https://www.auckland.ac.nz/en/study/study-options/find-a-study-option.html",
    "https://www.otago.ac.nz/courses",
    "https://www.wgtn.ac.nz/study/programmes-courses",
    "https://www.openpolytechnic.ac.nz/qualifications-and-courses/",
    "https://www.massey.ac.nz/study/all-qualifications-and-degrees/",

    # --- Canada ---
    "https://www.utoronto.ca/academics/programs-directory",
    "https://www.mcgill.ca/study/",
    "https://www.ubc.ca/academics/",
    "https://www.ualberta.ca/en/admissions-programs/",
    "https://www.yorku.ca/programs/",
    "https://www.queensu.ca/academics/programs",
    "https://www.uvic.ca/programs/",
    "https://www.sfu.ca/students/calendar/programs.html",

    # --- USA ---
    "https://www.asu.edu/programs/",
    "https://www.purdue.edu/academics/",
    "https://www.umass.edu/academics",
    "https://www.pennstateworldcampus.psu.edu/degrees-and-certificates/",
    "https://www.umgc.edu/online-degrees",
    "https://www.wgu.edu/online-degree-programs.html",
    "https://ecampus.oregonstate.edu/online-degrees/",
    "https://www.snhu.edu/online-degrees",

    # --- Europe / Asia / Africa (distance-learning reference) ---
    "https://www.ou.nl/en/-/study-offers",                    # Open Universiteit (NL)
    "https://www.uoc.edu/en/studies",                         # Open University of Catalonia (ES)
    "https://www.unisa.ac.za/sites/corporate/default/Apply-for-admission/Undergraduate-qualifications",
    "https://www.unisa.ac.za/sites/corporate/default/Apply-for-admission/Honours-degrees-&-postgraduate-diplomas",
    "https://www.ignou.ac.in/ignou/aboutignou/school",        # IGNOU (IN)
    "https://www.oum.edu.my/programmes/",                     # Open University Malaysia

]

KEYWORDS = ["bachelor", "master", "phd", "degree", "course", "programme", "tuition", "fee"]
CLOUDFLARE_SIGNS = ["just a moment", "enable javascript and cookies", "_cf_chl_opt"]#Cloudflareのチャレンジページに共通して見られるフレーズらしい
JS_SIGNS = ["<div id=\"app\"", "<div id=\"root\"", "__NEXT_DATA__", "window.__INITIAL_STATE__"]#ReactやVue、Next.jsなどのSPAでよく見られるHTMLの特徴　これらがある場合、BeautifulSoupだけではコンテンツを取得できない可能性が高い

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
