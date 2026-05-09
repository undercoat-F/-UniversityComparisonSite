import asyncio
import httpx
import requests
import json
import os
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser
import time
from datetime import datetime, timezone
from collections import defaultdict
import re
from xml.etree import ElementTree as ET

# target_url = ""

keywords = ["学位","学士","修士","博士",
            "degree", "bachelor","undergraduate","BSc","BA","BEng",
              "master","graduate","MSc","MA","MEng","MBA", 
              "phd","doctorate","doctoral","DSc","Ph.D.","Dr.",
              "program", "course", "study"]

'''
tuition
fees
cost
duration
credits
curriculum
'''
'''
queue       → 「実行待機中の仕事」(asyncio.Queue)
queued      → 「現在キュー内にある URL」のセット (set)
visited     → 「既に処理済み URL」のセット (set)
'''
depth = 2
# True: URL_Filterを適用 / False: URL_Filterを無効化
USE_URL_FILTER = True
#info_source = []
results = []
visited = set()
queued = set()
queue = asyncio.Queue()
filterCounter = 0
timeout = 30
#user_agent = "MyResearchCrawler/1.0"
#Accept-Encoding:gzip,deflate,br
headers = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/124.0.0.0 Safari/537.36'
    ),
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
}
worker_timeout = 300
worker_timeout_max = 3600 * 6
worker_timeout_extend = 120
worker_timeout_check_interval = 5
#user_agent ="Mozilla/5.0"
"""
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive"
"""

"""
Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36
"""

last_progress = time.monotonic()
stop_event = asyncio.Event() #EVENTは非同期でのシグナルのようなもの。（フラグ）
limit = asyncio.Semaphore(3) #同時にアクセスする数を制限するためのセマフォ
robots_parser = None
default_interval_sec = 0.5
host_crawl_delay = {}  # ホストごとのCrawl-delay（robots.txtから取得）
host_sitemaps = {}    # ホストごとのSitemap URLリスト（robots.txtのSitemap:ディレクティブから）
host_locks = defaultdict(asyncio.Lock)
lastaccess_by_host = {}
debug_http_logged = False
httpx_blocked_urls = []
httpx_blocked = 0
notfound_error = 0
notfound_urls = []
error_events = []
extraction_drop_stats = {
    "degree_line_hits": 0,
    "dropped_fee_context": 0,
    "dropped_non_numeric": 0,
    "kept_with_price": 0,
    "kept_without_price": 0,
}
excluded_page_count = 0

def add_error_log(url, stage, message, error_type="error", status_code=None):
    error_events.append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "url": url,
        "stage": stage,
        "error_type": error_type,
        "status_code": status_code,
        "message": str(message),
    })

def is_bot_check_page(html_text):
    text = (html_text or "").lower()
    bot_markers = [
        "captcha",
        "cloudflare",
        "verify you are human",
        "are you human",
        "access denied",
        "bot detection",
    ]
    return any(marker in text for marker in bot_markers)

def setup_robot_parser(base_url):
    parsed = urlparse(base_url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"

    rp = RobotFileParser()
    rp.set_url(robots_url)

    try:
        # urllib を使う rp.read() はサーバーに弾かれやすいので requests で取得する(自動でpythonスクリプトとわかるUser-Agentも付くため)
        resp = requests.get(robots_url, headers=headers, timeout=10)
        if resp.status_code == 200:#200:リクエスト成功
            rp.parse(resp.text.splitlines())
            # Crawl-delayを取得してホストごとに記録
            delay = rp.crawl_delay(headers['User-Agent']) or rp.crawl_delay('*')
            if delay:
                parsed2 = urlparse(base_url)
                host_crawl_delay[parsed2.netloc] = float(delay)
                print(f"Crawl-delay {delay}秒 を検出: {parsed2.netloc}")
            # Sitemapディレクティブを抽出
            sitemaps = [
                line.split(":", 1)[1].strip()
                for line in resp.text.splitlines()
                if line.strip().lower().startswith("sitemap:")
            ]
            if sitemaps:
                host_sitemaps[parsed.netloc] = sitemaps
                print(f"Sitemap {len(sitemaps)}件 を検出: {parsed.netloc}")
        elif resp.status_code in (401, 403):#401:認証必要、403:禁止
            # 仕様上は全拒否だが、実用上は許可として扱う（コンテンツは取得できるため）
            print(f"robots.txt が {resp.status_code} を返したため、クロールを許可として扱います: {robots_url}")
            return None
        else:
            print(f"robots.txt が {resp.status_code} を返しました。クロールを許可として扱います: {robots_url}")
            return None
        print(f"robots.txt を確認: {robots_url}")
        return rp
    except Exception as e:
        add_error_log(
            url=robots_url,
            stage="robots_txt",
            message=e,
            error_type="robots_read_failed"
        )
        print(f"robots.txt の取得に失敗: {robots_url} - {e}")
        return None

def can_fetch_url(url):
    if robots_parser is None:
        return True

    return robots_parser.can_fetch(headers['User-Agent'], url)

def fetch_sitemap_urls_sync(sitemap_url, allowed_netloc, visited_sitemaps=None):
    """sitemap.xml から allowed_netloc に属する URL を再帰的に収集する。
    sitemap index も処理する。取得失敗時は空リストを返す。"""

    if visited_sitemaps is None:
        visited_sitemaps = set()
    if sitemap_url in visited_sitemaps:
        return []
    visited_sitemaps.add(sitemap_url)

    try:
        resp = requests.get(sitemap_url, headers=headers, timeout=15)
        if resp.status_code != 200:
            print(f"  sitemap 取得失敗 ({resp.status_code}): {sitemap_url}")
            return []
        # Cloudflare 等の Bot ブロックを検出
        text_lower = resp.text[:500].lower()
        if "just a moment" in text_lower or "_cf_chl_opt" in text_lower:
            print(f"  sitemap が Bot ブロックされています: {sitemap_url}")
            return []

        root = ET.fromstring(resp.text)
        # namespace を除いたタグ名を取得
        tag = root.tag.split("}")[-1] if "}" in root.tag else root.tag
        ns = root.tag[: root.tag.rfind("}") + 1] if "}" in root.tag else ""

        if tag == "sitemapindex":
            # sitemap index → 子 sitemap を再帰処理
            urls = []
            for sitemap_elem in root.findall(f"{ns}sitemap"):
                loc_elem = sitemap_elem.find(f"{ns}loc")
                if loc_elem is not None and loc_elem.text:
                    urls.extend(fetch_sitemap_urls_sync(
                        loc_elem.text.strip(), allowed_netloc, visited_sitemaps
                    ))
            return urls

        if tag == "urlset":
            urls = []
            for url_elem in root.findall(f"{ns}url"):
                loc_elem = url_elem.find(f"{ns}loc")
                if loc_elem is not None and loc_elem.text:
                    loc = loc_elem.text.strip()
                    if urlparse(loc).netloc == allowed_netloc:
                        urls.append(loc)
            return urls

        print(f"  sitemap の形式が不明です (tag={tag}): {sitemap_url}")
        return []

    except Exception as e:
        print(f"  sitemap 解析エラー: {sitemap_url} - {e}")
        return []

async def fetch_with_requests(url, allowed_netloc=None):
    def _get():
        r = requests.get(url, headers=headers, timeout=timeout)
        # リダイレクト先が別ドメインの場合はスキップ
        if allowed_netloc and urlparse(r.url).netloc != allowed_netloc:
            raise ValueError(f"cross_domain_redirect: {r.url}")
        r.raise_for_status()
        return r.text
    return await asyncio.to_thread(_get)

async def fetch_page(session, url, allowed_netloc=None):
    global httpx_blocked, httpx_blocked_urls, notfound_error, notfound_urls, last_progress
    try:
        async with limit:
            await wait_hostslot(url)
            response = await session.get(url, follow_redirects=True)
            # httpxのリダイレクト先が別ドメインならスキップ
            if allowed_netloc and urlparse(str(response.url)).netloc != allowed_netloc:
                return None
            response.raise_for_status()
            last_progress = time.monotonic()
            html_text = response.text
            if is_bot_check_page(html_text):
                add_error_log(
                    url=url,
                    stage="fetch_page",
                    message="bot check page suspected",
                    error_type="bot_check_suspected",
                    status_code=response.status_code,
                )
            return html_text

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 403:
            httpx_blocked += 1
            httpx_blocked_urls.append(url)
            try:
                return await fetch_with_requests(url, allowed_netloc=allowed_netloc)
            except ValueError:
                # cross_domain_redirect: 別ドメインへのリダイレクト → 静かにスキップ
                last_progress = time.monotonic()
                return None
            except requests.HTTPError as re:
                #status_code = re.response.status_code if re.response is not None else None
                if re.response is not None:
                    status_code = re.response.status_code
                else:
                    status_code = None
                
                if status_code == 404:
                    notfound_error += 1
                    notfound_urls.append(url)
                    add_error_log(
                        url=url,
                        stage="fetch_with_requests",
                        message="HTTP 404 Not Found",
                        error_type="http_error",
                        status_code=404,
                    )
                    print(f"HTTP ERROR {url} (HTTP 404 Not Found)")
                    last_progress = time.monotonic()
                    return None

                add_error_log(
                    url=url,
                    stage="fetch_with_requests",
                    message=re,
                    error_type="requests_http_error",
                    status_code=status_code,
                )
                print(f"REQUESTS HTTP ERROR {url} - {re}")
                last_progress = time.monotonic()
                return None
            except requests.RequestException as re:
                add_error_log(
                    url=url,
                    stage="fetch_with_requests",
                    message=re,
                    error_type="requests_error",
                )
                print(f"REQUESTS ERROR {url} - {re}")
                last_progress = time.monotonic()
                return None
        elif e.response.status_code == 404:
            notfound_error += 1
            notfound_urls.append(url)
            add_error_log(
                url=url,
                stage="fetch_page",
                message="HTTP 404 Not Found",
                error_type="http_error",
                status_code=404,
            )
            print(f"HTTP ERROR {url} (HTTP 404 Not Found)")
            last_progress = time.monotonic()
            return None
        else:
            add_error_log(
                url=url,
                stage="fetch_page",
                message=f"HTTP {e.response.status_code}",
                error_type="http_error",
                status_code=e.response.status_code,
            )
            print(f"HTTP ERROR {url} (HTTP {e.response.status_code})")
            last_progress = time.monotonic()
            return None

    except httpx.RequestError as e:
        add_error_log(
            url=url,
            stage="fetch_page",
            message=e,
            error_type="httpx_request_error",
        )
        print(f"HTTPX CLIENT ERROR {url} - {e}")
        last_progress = time.monotonic()
        return None

async def wait_hostslot(url, slot_time=None):
    """同一ホストへのアクセス間隔を待つ（並列安全版）"""
    host = urlparse(url).netloc

    if slot_time is None:
        # robots.txtのCrawl-delayとデフォルトの大きい方を使う
        slot_time = max(default_interval_sec, host_crawl_delay.get(host, 0.0))

    #print(f"wait_hostslot: {host}")
    lock = host_locks[host]

    async with lock:
        now = time.monotonic()
        last_access = lastaccess_by_host.get(host, 0.0)
        elapsed = now - last_access
        wait_time = slot_time - elapsed

        if wait_time > 0:
            #print(f"同一ホストへのアクセス間隔を待機: {host} ({wait_time:.2f}秒)")
            await asyncio.sleep(wait_time)

        lastaccess_by_host[host] = time.monotonic()

def check_keywords_in_text(text, keywords):
    for keyword in keywords:
        if keyword in text:
            return True
    return False

def normalize_scope_path(url):
    path = urlparse(url).path.rstrip("/")
    return path or "/"

def is_url_in_scope(full_url, target_url):
    target_parsed = urlparse(target_url)
    full_parsed = urlparse(full_url)
    if full_parsed.netloc != target_parsed.netloc:
        return False

    scope_path = normalize_scope_path(target_url)
    candidate_path = full_parsed.path.rstrip("/") or "/"

    if scope_path == "/":
        return True

    return candidate_path == scope_path or candidate_path.startswith(scope_path + "/")

def should_exclude_course_page(url, title):
    text = f"{title} {urlparse(url).path}".lower()
    title_lower = (title or "").strip().lower()
    query = urlparse(url).query.lower()
    exclude_markers = [
        "scholarship",
        "bursar",
        "funding",
        "fellowship",
        "graduation",
        "alumni",
        "student guide",
        "support-wellbeing",
        "support and wellbeing",
        "recognition-prior-learning",
        "recognition of prior learning",
        "how-apply",
        "how to apply",
        "where-study",
        "where to study",
        "why-study-us",
        "why study with us",
        "on the day",
        "after-graduation",
        "after graduation",
        "am-qualified",
        "am i qualified",
        "costs-course",
        "costs of your course",
        "current-students",
        "student-services",
        "taster-courses",
        "benefits",
    ]

    list_page_titles = {
        "undergraduate programmes | degree finder | the university of edinburgh",
        "postgraduate taught programmes | degree finder | the university of edinburgh",
        "postgraduate research programmes | degree finder | the university of edinburgh",
        "undergraduate courses | university of london",
        "postgraduate courses | university of london",
        "research degrees | university of london",
    }

    if "page=" in query:
        return True
    if title_lower in list_page_titles:
        return True
    return any(marker in text for marker in exclude_markers)

def extract_urls(soup, base_url, target_url):
    urls = []
    for link in soup.find_all("a", href=True):
        href = link.get("href")
        full_url = urljoin(base_url, href)

        if is_url_in_scope(full_url, target_url):
            urls.append(full_url)

    return list(set(urls))

def is_non_html_url(url):
    """PDFや画像など、HTMLでないURLを判定（USE_URL_FILTERに関係なく常時適用）"""
    non_html_extensions = [
        ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
        ".zip", ".rar", ".tar", ".gz",
        ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp",
        ".mp4", ".mp3", ".avi", ".mov",
    ]
    base = url.lower().split("?")[0].split("#")[0]
    return any(base.endswith(ext) for ext in non_html_extensions)


def URL_Filter(url):

    bad_keywords = [
        "news", "event", "blog", "login",
        "contact", "about", "staff",
        "library"
    ]

    bad_extensions = [
        ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
        ".zip", ".rar", ".tar", ".gz",
        ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp",
        ".mp4", ".mp3", ".avi", ".mov",
    ]

    url_lower = url.lower().split("?")[0].split("#")[0]  # クエリ・フラグメントを除いて判定

    if any(url_lower.endswith(ext) for ext in bad_extensions):
        return True

    if any(k in url_lower for k in bad_keywords):
        return True

    return False

def should_queue_url(url, target_url):
    """URLを探索キューに入れてよいかを一箇所で判定する。"""
    if url in visited or url in queued:
        return False

    if not is_url_in_scope(url, target_url):
        return False

    if is_non_html_url(url):
        return False

    if USE_URL_FILTER and URL_Filter(url):
        return False

    if not can_fetch_url(url):
        return False

    return True

async def crawl(session, target_url):
    global last_progress, filterCounter, excluded_page_count
    allowed_netloc = urlparse(target_url).netloc
    while not stop_event.is_set():
        #url, current_depth = queue.popleft()    
        url,current_depth = await queue.get()
        queued.discard(url)
        last_progress = time.monotonic()

        try:

            if url in visited:
                continue
            if current_depth > depth:
                continue
            if not can_fetch_url(url):
                add_error_log(
                    url=url,
                    stage="crawl",
                    message="blocked by robots.txt",
                    error_type="robots_blocked",
                )
                print(f"robots.txt により取得をスキップ: {url}")
                continue

            visited.add(url)

            #print(f"{'  ' * current_depth}探索中: {url}")

            html = await fetch_page(session, url, allowed_netloc=allowed_netloc)
            if html is None:
                last_progress = time.monotonic()
                continue
            
            soup = BeautifulSoup(html, "html.parser")
            page_text = soup.get_text()

            if check_keywords_in_text(page_text, keywords):
                #print(f"  キーワード発見: {url}")
                record = extract_page(url, soup, page_text)
                if should_exclude_course_page(url, record.get("title", "")):
                    excluded_page_count += 1
                elif record["degrees"]:
                    results.append(record)

            links = extract_urls(soup, url, target_url)
            #print(f"links ={len(links)} depth={current_depth} url = {url}")

            #非同期では、すでにqueueに追加されているかもしれないからこれが必要
            if current_depth < depth:
                for link in links:
                    if should_queue_url(link, target_url):
                        queued.add(link)
                        await queue.put((link, current_depth + 1))
                        #last_progress = time.monotonic()
                        #print(f"  → キューに追加: {link}")
                    else:
                        filterCounter += 1
                        #print(f"  → フィルタリング: {link}")
            last_progress = time.monotonic()
        
        except Exception as e:
            add_error_log(
                url=url,
                stage="worker",
                message=e,
                error_type="worker_error",
            )
            print(f"[WORKER ERROR] url={url}, depth={current_depth}, error={e}")

        finally:
            queue.task_done()
#async def watcher(w,timeout=30):
async def watcher(timeout=180):
    global last_progress
    while True:
        await asyncio.sleep(2)
        if time.monotonic() - last_progress > timeout:
            print(f"[TIMEOUT] {timeout}秒間進捗なし。終了します。")
            # for w in workers:
            #     w.cancel()
            stop_event.set()
            return
        
#------------------------------------------
#情報抽出ロジック

#国情報はURLからの推定で取得する方が良いかもしれない
#timestampはクロールした日時を入れる
#visitedの正規化をチェックすること

def guess_country_from_url(url):
    #
    host = urlparse(url).netloc.lower()
    #
    if host.endswith(".ac.uk") or host.endswith(".gov.uk") or host.endswith(".uk"):
        return "UK"
    if host.endswith(".edu") or host.endswith(".gov"):
        return "US"
    if host.endswith(".ac.jp") or host.endswith(".go.jp") or host.endswith(".jp"):
        return "JP"
    return "unknown"

def canonicalize_url(url):
    # フラグメント/クエリ/末尾スラッシュ/年度セグメントを吸収して重複判定しやすくする
    x = url.strip().lower()
    x = re.sub(r"#.*$", "", x)
    x = re.sub(r"\?.*$", "", x)
    x = re.sub(r"/20\d{2}/", "/", x)
    x = x.rstrip("/")
    return x

def _keyword_hits(text, keyword):
    """英単語は単語境界で厳密一致、日本語などは部分一致で判定する。"""
    text_lower = text.lower()
    kw = keyword.lower()
    if re.search(r"[a-z]", kw):
        pattern = r"\b" + re.escape(kw) + r"\b"
        return len(re.findall(pattern, text_lower))
    return text_lower.count(kw)


def detect_course_type(primary_text, secondary_text=""):
    """重み付きスコア方式: 近傍文脈(primary)を優先し、ページ全体(secondary)を補助利用。"""
    course_type_keywords = {
        "computer_science": [
            "computer science", "informatics", "computing", "software", "programming", "ai", "artificial intelligence",
            "machine learning", "data science", "cybersecurity", "information systems", "情報", "データ", "計算機",
            "ソフトウェア", "人工知能", "機械学習", "情報科学",
        ],
        "engineering": [
            "engineering", "mechanical", "electrical", "electronic", "civil", "chemical engineering", "aerospace", "robotics",
            "materials", "industrial engineering", "工学", "機械", "電気", "電子", "土木", "化学工学", "材料", "ロボティクス",
        ],
        "business": [
            "business", "management", "finance", "mba", "accounting", "marketing", "economics and management",
            "entrepreneurship", "international business", "経営", "会計", "ビジネス", "ファイナンス", "マーケティング",
        ],
        "health": [
            "medicine", "medical", "nursing", "public health", "pharmacy", "biomedical", "clinical", "dentistry",
            "看護", "医学", "医療", "公衆衛生", "薬学", "歯学",
        ],
        "education": [
            "education", "teaching", "pedagogy", "curriculum", "teacher training", "educational", "教育", "教職", "教育学",
        ],
        "law": [
            "law", "legal", "jurisprudence", "llb", "llm", "法学", "法律", "司法",
        ],
        "social_science": [
            "psychology", "sociology", "politics", "political science", "economics", "international relations",
            "anthropology", "public policy", "社会", "心理", "経済", "政治", "国際関係", "社会学",
        ],
        "humanities": [
            "history", "philosophy", "literature", "language", "linguistics", "classics", "religion",
            "人文", "文学", "哲学", "歴史", "言語", "言語学",
        ],
        "science": [
            "biology", "chemistry", "physics", "mathematics", "science", "environmental science", "geology",
            "statistics", "生物", "化学", "物理", "数学", "理学", "統計", "地学", "環境科学",
        ],
        "arts_design": [
            "art", "design", "music", "fine art", "architecture", "media", "film", "theatre",
            "芸術", "デザイン", "音楽", "建築", "メディア", "映像", "演劇",
        ],
    }

    primary_lower = primary_text.lower()
    secondary_lower = secondary_text.lower()

    # 各カテゴリのスコアを計算
    # primary は強く効かせるため 3 倍、secondary は 1 倍で加点
    scores = {}
    primary_scores = {}
    secondary_scores = {}
    for course_type, words in course_type_keywords.items():
        primary_score = sum(_keyword_hits(primary_lower, word) for word in words)
        secondary_score = sum(_keyword_hits(secondary_lower, word) for word in words) if secondary_lower else 0
        primary_scores[course_type] = primary_score
        secondary_scores[course_type] = secondary_score
        scores[course_type] = (3 * primary_score) + secondary_score
    
    # 最高スコアを取得（スコア0なら"general"を返す）
    max_score = max(scores.values())
    if max_score == 0:
        return "general"
    
    # スコアが最高のカテゴリを抽出
    top_types = [k for k, v in scores.items() if v == max_score]
    if len(top_types) == 1:
        return top_types[0]

    # 同点時1: 近傍文脈(primary)一致数が多いカテゴリを優先
    best_primary = max(primary_scores[t] for t in top_types)
    top_types = [t for t in top_types if primary_scores[t] == best_primary]
    if len(top_types) == 1:
        return top_types[0]

    # 同点時2: ページ全体(secondary)一致数が多いカテゴリを優先
    best_secondary = max(secondary_scores[t] for t in top_types)
    top_types = [t for t in top_types if secondary_scores[t] == best_secondary]
    if len(top_types) == 1:
        return top_types[0]

    # 同点時3: 最終的な固定優先順（高頻度カテゴリへの偏りを抑える順）
    #この順がそのまま優先順になっている
    tie_break_priority = [
        "computer_science",
        "engineering",
        "health",
        "business",
        "law",
        "education",
        "social_science",
        "science",
        "humanities",
        "arts_design",
    ]
    for course_type in tie_break_priority:
        if course_type in top_types:
            return course_type

    # フォールバック
    return top_types[0]

def dedupe_degrees(degrees):
    unique = {}
    for d in degrees:
        key = (
            (d.get("context") or "").strip().lower(),
            (d.get("name") or "").strip().lower(),
            d.get("price"),
            (d.get("currency") or "").strip().upper(),
            (d.get("course_type") or "general").strip().lower(),
        )
        #if key not in unique:
        #    unique[key] = d

        if key not in unique:
            if not d.get("course_type"):
                d["course_type"] = "general"
            unique[key] = d

    return list(unique.values())

def degree_key(d):
    return (
        (d.get("context") or "").strip().lower(),
        (d.get("name") or "").strip().lower(),
        d.get("price"),
        (d.get("currency") or "").strip().upper(),
        (d.get("course_type") or "general").strip().lower(),
    )

def analyze_degree_duplicates(records):
    groups = {}
    total = 0
    for record in records:
        for d in record.get("degrees", []):
            total += 1
            key = degree_key(d)
            groups[key] = groups.get(key, 0) + 1

    dup_groups = 0
    dup_items = 0
    for count in groups.values():
        if count > 1:
            dup_groups += 1
            dup_items += count

    return {
        "degree_total": total,
        "degree_unique": len(groups),
        "degree_dup_groups": dup_groups,
        "degree_dup_items": dup_items,
    }


def classify_tuition(line_lower):
    """学費表記を固定コードで分類し、月額換算ルールを返す。"""
    if re.search(r"[0-9].{0,10}(\-|–|to).{0,10}[0-9]", line_lower):
        return "range", None, "range_not_normalized"
    if "per credit" in line_lower or "/credit" in line_lower:
        return "per_credit", None, "per_credit_not_normalized"
    if "per course" in line_lower or "/course" in line_lower:
        return "per_course", None, "per_course_not_normalized"
    if "per month" in line_lower or "/month" in line_lower or "monthly" in line_lower:
        return "fixed_month", 1, "monthly_as_is"
    if "per semester" in line_lower or "/semester" in line_lower:
        return "fixed_semester", 6, "semester_div_6"
    if "per year" in line_lower or "/year" in line_lower or "annual" in line_lower:
        return "fixed_year", 12, "yearly_div_12"
    if "total" in line_lower or "full program" in line_lower:
        return "total", None, "total_not_normalized"
    return "unknown", None, "unknown_not_normalized"


def detect_range_values(line):
    numbers = re.findall(r"([0-9]{1,3}(?:,[0-9]{3})+|[0-9]{4,})", line)
    if len(numbers) < 2:
        return None, None
    values = [int(x.replace(",", "")) for x in numbers]
    # 年度（2000〜2099）と思われる数値は除外
    values = [v for v in values if not (2000 <= v <= 2099)]
    if len(values) < 2:
        return None, None
    return min(values), max(values)

def extract_info(text, title=""):
    degree_keywords = ["bachelor", "master", "phd", "doctorate", "undergraduate", "graduate", "degree", "学士", "修士", "博士", "学位"]
    fee_keywords = [
        "tuition", "fee", "fees", "cost", "costs", "price", "prices", "funding",
        "international fee", "home fee", "uk fee", "overseas fee", "annual fee",
        "per year", "per semester", "per month", "full programme", "full program",
        "授業料", "費用", "学費",
    ]
    
    #degree_keywords = ["bachelor", "master", "phd", "doctorate", "undergraduate" "degree", "学士", "修士", "博士", "学位"]
    
    #degree_keywords = ["graduate", "program", "course", "study"]

    #カンマ付き数字も対応する価格抽出の正規表現　{1,3}は1000未満の数字、(?:,[0-9]{3})+はカンマと3桁の数字の繰り返し、|[0-9]{4,}は4桁以上の数字
    price_pattern = re.compile(r'(USD|EUR|GBP|JPY|AUD|CAD|\$|£|€|¥|円)?\s?([0-9]{1,3}(?:,[0-9]{3})+|[0-9]{4,})')
    #
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    degrees = []

    for idx, line in enumerate(lines):
        line_lower = line.lower()
        if not any(keyword in line_lower for keyword in degree_keywords):
            continue
        extraction_drop_stats["degree_line_hits"] += 1
        #
        matched_keyword = next(keyword for keyword in degree_keywords if keyword in line_lower)
        price_match = price_pattern.search(line)
        price = None
        currency = None
        if price_match is not None:
            currency = price_match.group(1) or None
            price = int(price_match.group(2).replace(",", ""))

        tuition_type, divisor_month, normalization_note = classify_tuition(line_lower)
        amount_min, amount_max = detect_range_values(line)
        normalized_monthly_amount = None
        if price is not None and divisor_month:
            normalized_monthly_amount = round(price / divisor_month, 2)

        # 金額がある行でも学費文脈が薄いものは除外してノイズを減らす
        # ただし現在行だけでは取りこぼしが多いため、近傍行も確認する。
        left = max(0, idx - 2)
        right = min(len(lines), idx + 3)
        fee_context_text = " ".join(lines[left:right]).lower()
        has_fee_context = any(k in fee_context_text for k in fee_keywords)
        has_currency_marker = re.search(r"\b(usd|eur|gbp|jpy|aud|cad)\b|[\$£€¥円]", fee_context_text) is not None
        if price is not None and not has_fee_context and not has_currency_marker:
            extraction_drop_stats["dropped_fee_context"] += 1
            continue

        # 数字すらない学位行はノイズが多いため除外
        if price is None and not re.search(r"[0-9]", line):
            extraction_drop_stats["dropped_non_numeric"] += 1
            continue

        if currency == "$":
            currency = "USD"
        elif currency == "£":
            currency = "GBP"
        elif currency == "€":
            currency = "EUR"
        elif currency == "¥":
            currency = "JPY"
        elif currency == "円":
            currency = "JPY"

    #価格がない場合は残さない

        # 1行判定だと情報不足なので、前後行 + タイトルを含めた局所文脈を作る
        left = max(0, idx - 6)
        right = min(len(lines), idx + 7)
        local_context = " ".join(lines[left:right])
        primary_text = f"{title} {local_context}".strip()

        degrees.append({
            "name": matched_keyword.title(),
            "price": price,
            "currency": currency,
            "tuition_type": tuition_type,
            "amount_min": amount_min,
            "amount_max": amount_max,
            "normalized_monthly_amount": normalized_monthly_amount,
            "normalization_note": normalization_note,
            "course_type": detect_course_type(primary_text, text),
            "is_online": "online" in line_lower,
            "limit": "deadline" if "deadline" in line_lower else None,#期日などの締め切り情報があるかどうか
            "context": line,
        })

    for d in degrees:
        if d.get("price") is None:
            extraction_drop_stats["kept_without_price"] += 1
        else:
            extraction_drop_stats["kept_with_price"] += 1

    #長すぎるテキストは除外
    for d in degrees:
        if len(d["context"]) > 100:
            d["context"] = d["context"][:100] + "..."
    
    degrees = dedupe_degrees(degrees)

    #ルートURLを学位ページからにする方が良いかも

    return degrees

def extract_page(url, soup, page_text):
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    raw_text = " ".join(page_text.split())
    degrees = extract_info(page_text, title)

    return {
        "url": url,
        "title": title,
        "country": guess_country_from_url(url),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "degrees": degrees,
        "raw_text": raw_text,
        "source_type": "html",
    }

def dedupe_records(records):
    unique = {}
    for record in records:
        record["degrees"] = dedupe_degrees(record.get("degrees", []))
        key = (canonicalize_url(record.get("url", "")), record.get("title", "").strip().lower())
        if key not in unique:
            unique[key] = record
            continue

        # 同一ページが重複した場合は学位配列を統合してから重複除去する
        prev = unique[key]
        merged_degrees = prev.get("degrees", []) + record.get("degrees", [])
        prev["degrees"] = dedupe_degrees(merged_degrees)

        # 情報量が増える場合のみ補足情報を更新
        if len(record.get("raw_text", "")) > len(prev.get("raw_text", "")):
            prev["raw_text"] = record.get("raw_text", "")
        if not prev.get("title") and record.get("title"):
            prev["title"] = record.get("title")
    return list(unique.values())

# def dedupe_across_records(records):
#     # 全ページ横断で degree の重複を除去する
#     seen = set()
#     new_records = []

#     for record in records:
#         kept_degrees = []
#         for d in record.get("degrees", []):
#             key = degree_key(d)
#             if key in seen:
#                 continue
#             seen.add(key)
#             kept_degrees.append(d)

#         if kept_degrees:
#             updated = dict(record)
#             updated["degrees"] = kept_degrees
#             new_records.append(updated)

#     return new_records

def save_json(records, file_path="crawler/results.json"):
    raw_record_count = len(records)
    records = dedupe_records(records)
    # records = dedupe_across_records(records)
    record_count = len(records)
    degree_stats = analyze_degree_duplicates(records)

    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

    return {
        "record_raw": raw_record_count,
        "record_saved": record_count,
        **degree_stats,
    }

'''
keywords = ["学位","学士","修士","博士",
            "degree", "bachelor","undergraduate","BSc","BA","BEng",
              "master","graduate","MSc","MA","MEng","MBA", 
              "phd","doctorate","doctoral","DSc","Ph.D.","Dr.",
              "program", "course", "study"]
'''

'''
1大学あたりのデータ構造
{
  "url": "...",
  "title": "...",
  "country": "...",
  "timestamp": "...",

  "degrees": [
    {
      "name": "...",
      "price": 1000,
      "currency": "USD",
      "is_online": true,
      "limit": "...",
      "context": "..."
    }
  ],

  "raw_text": "...",
  "source_type": "..."
}
'''


#------------------------------------------


async def main(target_url, crawl_depth=None, log_dt=None):
    global robots_parser, last_progress, worker_timeout, worker_timeout_max, worker_timeout_extend, worker_timeout_check_interval
    global results, visited, filterCounter, httpx_blocked_urls, httpx_blocked, notfound_error, notfound_urls, error_events, depth
    global host_sitemaps
    global extraction_drop_stats
    global excluded_page_count
    #global target_url

    if log_dt is None:
        log_dt = datetime.now().strftime("%Y%m%d_%H%M%S")

    os.makedirs("log", exist_ok=True)

    if not target_url:
        target_url = input("対象URLを入力してください: ").strip()  # 空白対策

    if crawl_depth is not None:
        depth = crawl_depth

    print("クロール開始...")

    # 複数URL連続実行時のためにグローバル状態をリセット
    results.clear()
    visited.clear()
    filterCounter = 0
    httpx_blocked_urls.clear()
    httpx_blocked = 0
    notfound_error = 0
    notfound_urls.clear()
    error_events.clear()
    excluded_page_count = 0
    extraction_drop_stats = {
        "degree_line_hits": 0,
        "dropped_fee_context": 0,
        "dropped_non_numeric": 0,
        "kept_with_price": 0,
        "kept_without_price": 0,
    }
    worker_timeout = 300

    stop_event.clear()
    queued.clear()
    last_progress = time.monotonic()
    robots_parser = setup_robot_parser(target_url)

    # sitemapからURL取得を試みる（成功すれば直接詳細ページをキューに積む）
    sitemap_seed_count = 0
    target_netloc = urlparse(target_url).netloc
    if target_netloc in host_sitemaps:
        print(f"sitemapからURL取得を試みます...")
        sm_urls = []
        for sm_url in host_sitemaps[target_netloc]:
            fetched = await asyncio.to_thread(fetch_sitemap_urls_sync, sm_url, target_netloc)
            sm_urls.extend(fetched)
        # target_url のスコープ以下にURLを絞り込み
        sm_urls = list(dict.fromkeys(u for u in sm_urls if is_url_in_scope(u, target_url)))
        if sm_urls:
            print(f"sitemapから {len(sm_urls)} 件のURLを取得 (クロール不要)")
            for u in sm_urls:
                queued.add(u)
                await queue.put((u, 0))
            sitemap_seed_count = len(sm_urls)
        else:
            print(f"sitemapに{target_url}以下のURLがないためクロールフォールバック")

    if sitemap_seed_count == 0:
        # sitemap がない or 失敗 → 通常クロール
        queued.add(target_url)
        await queue.put((target_url, 0))  # 最初の仕事を投入

    client_timeout = httpx.Timeout(15.0)
    async with httpx.AsyncClient(timeout=client_timeout, headers=headers) as session:
        workers = [asyncio.create_task(crawl(session, target_url)) for _ in range(3)]
        watcher_task = asyncio.create_task(watcher())

        start_time = time.monotonic()
        last_seen_progress = last_progress

        try:
            while True:
                if stop_event.is_set():
                    print("[STOP] タイムアウトイベントが発生しました。")
                    break

                elapsed = time.monotonic() - start_time
                remaining = worker_timeout - elapsed
                if remaining <= 0:
                    print(f"[TIMEOUT] 全体処理が {int(worker_timeout)}秒を超えました。")
                    stop_event.set()
                    break

                try:
                    await asyncio.wait_for(
                        queue.join(),
                        timeout=min(worker_timeout_check_interval, remaining)
                    )
                    break
                except asyncio.TimeoutError:
                    if last_progress > last_seen_progress and worker_timeout < worker_timeout_max:
                        worker_timeout = min(worker_timeout + worker_timeout_extend, worker_timeout_max)
                        last_seen_progress = last_progress
                        print(f"[EXTEND] 進捗あり。全体上限を {int(worker_timeout)} 秒に延長")
        finally:
            for w in workers:
                w.cancel()#眠っているワーカーをキャンセル
            watcher_task.cancel()

            await asyncio.gather(*workers, watcher_task, return_exceptions=True)

    # with open("found_urls.txt", "w", encoding="utf-8") as f:
    #     for url in info_source:
    #         f.write(url + "\n")
    with open("log/httpx_blocked_urls.txt", "w", encoding="utf-8") as f:
        for url in httpx_blocked_urls:
            f.write(url + "\n")
    with open("log/notfound_urls.txt", "w", encoding="utf-8") as f:
        for url in notfound_urls:
            f.write(url + "\n")

    with open(f"log/error_log_{log_dt}.txt", "a", encoding="utf-8") as f:
        f.write(f"--- {target_url} ---\n")
        if not error_events:
            f.write("NO_ERRORS\n")
        else:
            for e in error_events:
                f.write(
                    f"[{e['timestamp']}] type={e['error_type']} stage={e['stage']} "
                    f"status={e['status_code']} url={e['url']} message={e['message']}\n"
                )
        f.write("\n")

    stats = save_json(results)

    # print(f"訪問したURL数: {len(visited)}")
    # print(f"httpxがブロックされたURL数: {len(httpx_blocked_urls)}")
    # print(f"フィルタリングされたURL数: {filterCounter}")
    # print(f"キーワードが見つかったURL数(保存前): {stats['record_raw']}")
    # print(f"キーワードが見つかったURL数(重複除去後): {stats['record_saved']}")
    # print(f"学位レコード数(合計): {stats['degree_total']}")
    # print(f"学位レコード数(ユニーク key=name+price+currency+course_type): {stats['degree_unique']}")
    # print(f"学位重複グループ数(key一致): {stats['degree_dup_groups']}")
    # print(f"学位重複件数(key一致): {stats['degree_dup_items']}")
    # print(f"HTTP 404 Not Found のURL数: {len(notfound_urls)}")
    # print(f"全体実行時間: {int(time.monotonic() - start_time)}秒")

    # サイトごとのログを追記（全体ログは crawl_log_{dt}.txt に蓄積）
    timestamp_now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(f"log/crawl_log_{log_dt}.txt", "a", encoding="utf-8") as f:
        f.write(f"{'='*60}\n")
        f.write(f"[{timestamp_now}] {target_url}\n")
        f.write(f"{'='*60}\n")
        f.write(f"訪問したURL数: {len(visited)}\n")
        f.write(f"httpxがブロックされたURL数: {len(httpx_blocked_urls)}\n")
        f.write(f"エラーログ件数: {len(error_events)}\n")
        f.write(f"sitemap使用: {'あり (' + str(sitemap_seed_count) + ' URL)' if sitemap_seed_count else 'なし（クロール方式）'}\n")
        f.write(f"フィルタリングされたURL数: {filterCounter}\n")
        f.write(f"タイトル除外ページ数: {excluded_page_count}\n")
        f.write(f"キーワードが見つかったURL数(保存前): {stats['record_raw']}\n")
        f.write(f"キーワードが見つかったURL数(重複除去後): {stats['record_saved']}\n")
        f.write(f"学位レコード数(合計): {stats['degree_total']}\n")
        f.write(f"学位レコード数(ユニーク key=name+price+currency+course_type): {stats['degree_unique']}\n")
        f.write(f"学位重複グループ数(key一致): {stats['degree_dup_groups']}\n")
        f.write(f"学位重複件数(key一致): {stats['degree_dup_items']}\n")
        f.write(
            f"抽出内訳: degree行={extraction_drop_stats['degree_line_hits']} "
            f"fee文脈除外={extraction_drop_stats['dropped_fee_context']} "
            f"非数値除外={extraction_drop_stats['dropped_non_numeric']} "
            f"保存(価格あり)={extraction_drop_stats['kept_with_price']} "
            f"保存(価格なし)={extraction_drop_stats['kept_without_price']}\n"
        )
        f.write(f"HTTP 404 Not Found のURL数: {len(notfound_urls)}\n")
        f.write(f"全体実行時間: {int(time.monotonic() - start_time)}秒\n")
        f.write("\n")

if __name__ == "__main__":
    asyncio.run(main())
