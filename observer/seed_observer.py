from dataclass.dataclass import SeedDiscovery
import time
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse
import re
from urllib.robotparser import RobotFileParser
from dataclass.dataclass import PageAnalysis,ContentType
import pdfplumber
import io
from typing import Any, Optional

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

DEFAULT_TIMEOUT = 1.0  # seconds

"""
ページ取得
↓
特徴抽出
↓
ページ種別判定
↓
専用抽出器
↓
UniversityCandidate生成
↓
検索API
↓
SeedDiscovery生成
"""

"""
タグ集計
↓
PageAnalysis
↓
candidate_lines
↓
正規化
↓
検索API
"""

Seed_State = SeedDiscovery(domain_url="", seed_urls=[], depth=None)
ThisPage = PageAnalysis()


def normalize_domainurl(domain_or_url: str) -> str:
    s = (domain_or_url or "").strip()
    if not s:
        raise ValueError("empty domain/url")
    if "://" not in s:
        s = "https://" + s
    p = urlparse(s)
    if not p.netloc:
        raise ValueError(f"invalid domain/url: {domain_or_url}")
    return f"{p.scheme}://{p.netloc}"


def get_crawl_delay(domain: str) -> float:
    #ここでrobots.txtを取得して、クロールディレイを解析する
    #監視用クローラーはまだ非同期でなくてもよいと思われる
    robots_url = f"{normalize_domainurl(domain)}/robots.txt"

    robots_text = None
    if robots_text is None:
        try:
            requests_response = requests.get(robots_url, headers=DEFAULT_HEADERS, timeout=DEFAULT_TIMEOUT, allow_redirects=True)
            if requests_response.status_code == 200:
                robots_text = requests_response.text
        except requests.RequestException:
            Seed_State.add_log(robots_url, status_code=None, error="requests.RequestError")  # robots.txt の取得に失敗したことを記録
            pass

    if robots_text is not None:
        robots_parser = RobotFileParser()
        robots_parser.set_url(robots_url)
        robots_parser.parse(robots_text.splitlines())
        crawl_delay = robots_parser.crawl_delay("*")

        if crawl_delay is None:
            crawl_delay = DEFAULT_TIMEOUT  # デフォルトのクロールディレイを設定

        return crawl_delay

    return DEFAULT_TIMEOUT
    
def pagetype_analyze(url: str, html: str) -> PageAnalysis:
    # ここでページのHTMLを解析して、PageTypeを判定する
    global ThisPage
    ThisPage = PageAnalysis()

    response = requests.get(url, headers=DEFAULT_HEADERS, timeout=DEFAULT_TIMEOUT, allow_redirects=True)
    ThisPage.response = response
    response_content_type = response.headers.get("Content-Type", "").lower()

    if response_content_type.startswith("application/pdf"):
        ThisPage.content_type = ContentType.PDF
    elif response_content_type.startswith("text/html"):
        ThisPage.content_type = ContentType.HTML
    elif response_content_type.startswith("image/"):
        ThisPage.content_type = ContentType.IMAGE
    elif response_content_type.startswith("application/json"):
        ThisPage.content_type = ContentType.JSON
    else:
        ThisPage.content_type = ContentType.OTHER

    if ThisPage.content_type == ContentType.HTML:
        soup = BeautifulSoup(html or "", "html.parser")

        all_tags = soup.find_all(True)
        tag_counts: dict[str, int] = {}
        for tag in all_tags:
            tag_counts[tag.name] = tag_counts.get(tag.name, 0) + 1

        table_count = tag_counts.get("table", 0)
        form_count = tag_counts.get("form", 0)
        div_count = tag_counts.get("div", 0)

        # class/id に search 系キーワードが含まれる div を検索フォーム候補として数える
        search_div_count = 0
        detail_div_count = 0
        for div in soup.find_all("div"):
            classes = " ".join(div.get("class", []))
            attrs = f"{classes} {div.get('id', '')}".lower()
            if any(k in attrs for k in ("search", "finder", "filter", "query")):
                search_div_count += 1
            if any(k in attrs for k in ("profile", "detail", "program", "course-detail")):
                detail_div_count += 1

        # 優先順位: table_list > search_form > profile
        if table_count >= 10:
            ThisPage.table_list = True
        elif form_count >= 1 or search_div_count >= 3:
            ThisPage.search_form = True
        elif detail_div_count >= 2 or (div_count >= 10 and search_div_count == 0):
            ThisPage.profile = True
        else:
            ThisPage.text = True

    return ThisPage

    #HTMLから取れる場合
        #例: TABLEタグが多い → TABLE_LIST 
            #tr>tbody>table といった数と思われる
            #table関連タグが多い場合、tableタグの中身を見て、～大学、~University、～College、～Institute などの文字列が含まれるかを確認する
            #aタグ、trタグ等、色々なタグの中にある場合があると思われるので、tableタグの中身を見て文字列判定の方が精度が高いと思われる
        #検索フォームと判定 → SEARCH_FORM
            #divタグに serarch という文字列が含まれたタグが多い　その数で判定して、何も選択せず検索ボタンをクリックさせ、大学一覧を出す
            #検索フォームから飛んだ大学詳細ページ → PROFILE
                #詳細ページもtablelistだったりする　その場合はtablelistとする
                #そうでない場合をsearch_formとして、あとから自分で調べてクローラー改善の足しにする
    #PDFから取れる場合 →　PDF
        # PDFには3種類ある
        # 1. テキスト埋め込みPDF → pdfplumberで取れる
        # 2. 表PDF → pdfplumber / camelot / tabula が候補
        # 3. 画像PDF → OCRが必要
        # 今回は３は非対応とする

def extract_candidate_lines(ThisPage : PageAnalysis) -> list[str]:
    # ここでページのHTMLあるいはPDFを解析して、大学名候補の行を抽出する
    #HTMLの場合は、soupから大学名候補の行を抽出する
    #PDFの場合は、pdfplumberなどでテキストを抽出して、大学名候補の行を抽出する
    candidate_lines: list[str] = []
    if ThisPage.content_type == ContentType.HTML:
        #HTMLから大学名候補の行を抽出する
        #例: tableタグの中に、～大学、~University、～College、～Institute などの文字列が含まれる行を抽出する
        soup = BeautifulSoup(ThisPage.response.text, "html.parser")
        for table in soup.find_all("table"):
            for row in table.find_all("tr"):
                row_text = row.get_text(separator=" ", strip=True)
                if any(k in row_text for k in ("大学", "University", "College", "Institute")):
                    candidate_lines.append(row_text)
    
    elif ThisPage.content_type == ContentType.PDF:
        #PDFから大学名候補の行を抽出する
        #例: pdfplumberなどでテキストを抽出して、～大学、~University、～College、～Institute などの文字列が含まれる行を抽出する

        with pdfplumber.open(io.BytesIO(ThisPage.response.content)) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    for line in text.splitlines():
                        if any(k in line for k in ("大学", "University", "College", "Institute")):
                            candidate_lines.append(line.strip())

    ThisPage.candidate_lines = candidate_lines

def extract_universitynamelist(ThisPage : PageAnalysis) -> list[str]:
    # ここでcandidate_linesから大学名を正規化して抽出する
    #例: ～大学、~University、～College、～Institute などの文字列が含まれる行から、大学名だけを抽出して正規化する

    university_name_list: list[str] = []
    #jp_pattern = re.compile(r"[^\s|｜/／:：><\(\)\[\]【】]{1,60}(?:大学院|大学|短期大学|専門職大学|高等専門学校|専門学校)")
    jp_pattern = re.compile(r"[^\s|｜/／:：><\(\)\[\]【】]{1,60}(?:大学院|大学(?!院)|短期大学|専門職大学|高等専門学校|専門学校)")
    en_patterns = [
        re.compile(
            r"\b(?:The\s+)?(?:[A-Z][A-Za-z&'.\-]*|of|and|for|the){1,12}\s+"
            r"(?:University|College|Institute|School|Polytechnic)"
            r"(?:\s+of\s+(?:[A-Z][A-Za-z&'.\-]*|the|and|for){1,8})?\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(?:University|College|Institute|School|Polytechnic)\s+of\s+"
            r"(?:[A-Z][A-Za-z&'.\-]*|the|and|for){1,10}\b",
            re.IGNORECASE,
        ),
    ]

    noise_tokens = {
        "admissions", "admission", "apply", "application", "course", "courses", "program", "programs",
        "tuition", "fees", "fee", "ranking", "rankings", "overview", "home", "official", "website",
        "contact", "news", "blog", "events", "scholarship", "scholarships", "entry", "requirements",
        "入試", "募集要項", "一覧", "学費", "偏差値", "案内", "情報", "公式", "ホームページ", "問い合わせ",
    }

    def normalize_jp_name(name: str) -> str:
        cleaned = re.sub(r"\s+", "", name)
        cleaned = re.sub(r"[\(\[【].*?[\)\]】]", "", cleaned)
        #cleaned = re.sub(r"大学院|短期大学|専門職大学|高等専門学校|専門学校|大学", "", cleaned)
        # 最後の接尾辞までを大学名として保持し、その後ろを除去する
        _suffix_pat = re.compile(r"大学院|短期大学|専門職大学|高等専門学校|専門学校|大学")
        matches = list(_suffix_pat.finditer(cleaned))
        if matches:
            cleaned = cleaned[: matches[-1].end()]
        return cleaned.strip("|｜/／:：><()[]{}【】。、,.・- ")

    def normalize_en_name(name: str) -> str:
        cleaned = re.sub(r"\s+", " ", name).strip("|｜/／:：><()[]{}【】。、,.・- ")
        cleaned = re.sub(r"\b(admissions?|apply|application|courses?|programs?|tuition|fees?|ranking|overview|home|official|website|contact|news|events)\b.*$", "", cleaned, flags=re.IGNORECASE)
        cleaned = cleaned.strip("|｜/／:：><()[]{}【】。、,.・- ")
        return cleaned

    def is_noisy(name: str) -> bool:
        lowered = name.lower()
        if len(name) < 3:
            return True
        if lowered in noise_tokens:
            return True
        if re.fullmatch(r"(?:University|College|Institute|School|Polytechnic)", name, flags=re.IGNORECASE):
            return True
        return False

    def add_name(name: str, is_jp: bool) -> None:
        cleaned = normalize_jp_name(name) if is_jp else normalize_en_name(name)
        if not cleaned or is_noisy(cleaned):
            return
        if cleaned not in university_name_list:
            university_name_list.append(cleaned)

    for line in ThisPage.candidate_lines:
        normalized_line = line.replace("　", " ").strip()
        if not normalized_line:
            continue

        segments = [seg.strip() for seg in re.split(r"[|｜/／>＞:：;；]+", normalized_line) if seg.strip()]
        if not segments:
            segments = [normalized_line]

        for seg in segments:
            for match in jp_pattern.findall(seg):
                add_name(match, is_jp=True)

            for en_pattern in en_patterns:
                for match in en_pattern.findall(seg):
                    add_name(match, is_jp=False)

    ThisPage.extracted_universitynamelist = university_name_list
    return university_name_list

    #手順
        # 1. PageType判定
        # 2. candidate_lines抽出
        # 3. university_name正規化
        # 4. 検索API接続

def write_log(url: str, status_code: Optional[int], error: Optional[str] = None, step: str = "observe") -> None:
    Seed_State.add_log(url, status_code=status_code, error=error, step=step)

# def observe_url(url: str, score: float) -> None:
#     url = url.strip()
#     if not url:
#         #ログを入れてもよい
#         write_log(url, status_code=None, error="Empty URL", step="observe")
#         return None
#     #ページ全体のテキストから、大学名候補リストを作成
#     try:
#         domain = urlparse(url).netloc
#         crawl_delay = get_crawl_delay(domain)
#         time.sleep(crawl_delay)  # クロールディレイを考慮して待機
#         response = requests.get(url, headers=DEFAULT_HEADERS, timeout=DEFAULT_TIMEOUT, allow_redirects=True)
    
#         if response.status_code == 200:
#             Seed_State.add_log(url, status_code=200, step="observe")
#             soup = BeautifulSoup(response.text, "html.parser")
#             #ここでsoupからさらにURLを抽出して、Seed_Stateに追加することもできる
#             #例: aタグのhref属性からURLを抽出するなど
    
#     except requests.RequestException as exc:
#         Seed_State.add_log(url, status_code=None, error=f"requests.RequestException: {exc}", step="observe")

    
#     Seed_State.add_seed_candidate(url, score)

def observe_url(url: str) -> Optional[PageAnalysis]:
    url = url.strip()
    if not url:
        write_log(url, status_code=None, error="Empty URL", step="observe")
        return None

    try:
        domain = urlparse(url).netloc
        crawl_delay = get_crawl_delay(domain)
        time.sleep(crawl_delay)  # クロールディレイを考慮して待機
        response = requests.get(url, headers=DEFAULT_HEADERS, timeout=DEFAULT_TIMEOUT, allow_redirects=True)

        page_analysis = pagetype_analyze(url, response.text)

        extract_candidate_lines(page_analysis)
        extract_universitynamelist(page_analysis)

        if response.status_code == 200:
            Seed_State.add_log(url, status_code=200, step="observe")
            soup = BeautifulSoup(response.text, "html.parser")
            #ここでsoupからさらにURLを抽出して、Seed_Stateに追加することもできる
            #例: aタグのhref属性からURLを抽出するなど

        return page_analysis

    except requests.RequestException as exc:
        Seed_State.add_log(url, status_code=None, error=f"requests.RequestException: {exc}", step="observe")
        return None
