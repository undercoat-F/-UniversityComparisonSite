from crawler.crawlAndSaver import main as crawl_main
from db.jsontocsv import main as json_to_csv_main
from db.db_saver import main as db_saver_main
import asyncio
import os
import shutil
from datetime import datetime
import traceback
from urllib.parse import urlparse
from requests.exceptions import HTTPError


# (URL, depth) のタプル形式。depth省略時はcrawlAndSaver.pyのデフォルト値(depth=2)が使われる
searchURLs = [
    # 追加候補（check_site.py でOK確認済み）
    ("https://study.ed.ac.uk/programmes", 1),
    ("https://www.london.ac.uk/study/courses", 1),

    #("https://study.ed.ac.uk/postgraduate/fees-funding/tuition-fees/deposits", 2),
    ("https://study.ed.ac.uk/programmes/undergraduate?query=", 1),
    ("https://study.ed.ac.uk/programmes/postgraduate-taught", 1),
    ("https://study.ed.ac.uk/programmes/postgraduate-research", 1),

    # 以下はJSレンダリングサイトのため取得不可 → 開発者ツールでDOM確認後に再検討
    # ("https://www.open.ac.uk/courses/", 2),                                          # Cloudflare Bot保護確認済み、不可
    
    ("https://www.london.ac.uk/study/courses/undergraduate", 1),                     # check_site.pyでOK確認済み
    ("https://www.london.ac.uk/study/courses/postgraduate", 1),                      # check_site.pyでOK確認済み
    ("https://www.london.ac.uk/study/courses/research-degree", 1),                   # check_site.pyでOK確認済み
    # ("https://www.london.ac.uk/study/women-in-stem", 2),                           # 範囲が広くノイズが多いため既定ETL対象から除外
    
    # ("https://www.athabascau.ca/programs/index.html#/undergraduate/all/all", 2),     # JSサイト確認済み (SPAハッシュルーティング)
    # ("https://www.athabascau.ca/programs/index.html#/graduate/all", 2),              # JSサイト確認済み　Cloudflare Bot保護確認済み、不可
    # ("https://www.athabascau.ca/course/index.html#/undergraduate/all/all", 2),       # JSサイト確認済み　Cloudflare Bot保護確認済み、不可
    # ("https://www.athabascau.ca/programs-courses/professional-development.html", 2), # JSサイト確認済み　Cloudflare Bot保護確認済み、不可
    
    # ("https://www.ignou.ac.in/schools/programmes/0?nav=49", 1),                      # JSサイト確認済み　Cloudflare Bot保護確認済み、不可

    # =====================================================================
    # 国別追加候補（Top50参考 + 一覧ページ中心）
    # 使い方:
    #   1) check_site.py で OK 判定を確認
    #   2) 必要な行だけコメント解除
    #   3) 初回は depth=1 で運用
    # =====================================================================

    # --- UK ---
     ("https://www.manchester.ac.uk/study/undergraduate/courses/", 1),
     ("https://www.manchester.ac.uk/study/masters/courses/list/", 1),
     ("https://www.birmingham.ac.uk/study/undergraduate/courses", 1),
     ("https://www.birmingham.ac.uk/study/postgraduate/taught/courses", 1),
     ("https://www.bristol.ac.uk/study/undergraduate/courses/", 1),
     ("https://www.bristol.ac.uk/study/postgraduate/taught/courses/", 1),
     ("https://www.leeds.ac.uk/undergraduate-courses", 1),
     ("https://courses.leeds.ac.uk/", 1),
     ("https://www.southampton.ac.uk/courses/undergraduate", 1),
     ("https://www.southampton.ac.uk/courses/postgraduate-taught", 1),
     ("https://www.york.ac.uk/study/undergraduate/courses/", 1),
     ("https://www.york.ac.uk/study/postgraduate-taught/courses/", 1),
     ("https://www.exeter.ac.uk/study/undergraduate/courses/", 1),
     ("https://www.exeter.ac.uk/study/postgraduate/courses/", 1),
     ("https://www.sheffield.ac.uk/undergraduate/courses", 1),
     ("https://www.sheffield.ac.uk/postgraduate/taught/courses", 1),

    # --- Ireland ---
    # ("https://www.ucd.ie/courses/", 1),
     ("https://www.tcd.ie/courses/", 1),
     ("https://www.universityofgalway.ie/courses/", 1),
     ("https://www.ucc.ie/en/study/courses/", 1),

    # --- Australia ---
     ("https://www.sydney.edu.au/courses/", 1),
    # ("https://study.unimelb.edu.au/find", 1),
     ("https://www.unsw.edu.au/study", 1),
    # ("https://www.monash.edu/study/courses", 1),
    # ("https://www.uq.edu.au/study/options", 1),
     ("https://www.adelaide.edu.au/degree-finder/", 1),
     ("https://www.anu.edu.au/study", 1),
    # ("https://www.deakin.edu.au/course", 1),
     ("https://www.cdu.edu.au/study", 1),
     ("https://www.latrobe.edu.au/courses", 1),
     ("https://www.murdoch.edu.au/study", 1),
    # ("https://www.utas.edu.au/courses", 1),
     ("https://www.vu.edu.au/study-at-vu/courses", 1),

    # --- New Zealand ---
     ("https://www.auckland.ac.nz/en/study/study-options/find-a-study-option.html", 1),
    # ("https://www.otago.ac.nz/courses", 1),
     ("https://www.wgtn.ac.nz/study/programmes-courses", 1),
     ("https://www.openpolytechnic.ac.nz/qualifications-and-courses/", 1),
     ("https://www.massey.ac.nz/study/all-qualifications-and-degrees/", 1),

    # --- Canada ---
    # ("https://www.utoronto.ca/academics/programs-directory", 1),
    # ("https://www.mcgill.ca/study/", 1),
    # ("https://www.ubc.ca/academics/", 1),
    # ("https://www.ualberta.ca/en/admissions-programs/", 1),
    # ("https://www.yorku.ca/programs/", 1),
    # ("https://www.queensu.ca/academics/programs", 1),
    # ("https://www.uvic.ca/programs/", 1),
    # ("https://www.sfu.ca/students/calendar/programs.html", 1),

    # --- USA ---
    # ("https://www.asu.edu/programs/", 1),
    # ("https://www.purdue.edu/academics/", 1),
    # ("https://www.umass.edu/academics", 1),
    # ("https://www.pennstateworldcampus.psu.edu/degrees-and-certificates/", 1),
    # ("https://www.umgc.edu/online-degrees", 1),
    # ("https://www.wgu.edu/online-degree-programs.html", 1),
    # ("https://ecampus.oregonstate.edu/online-degrees/", 1),
    # ("https://www.snhu.edu/online-degrees", 1),

    # --- Europe / Asia / Africa (distance-learning reference) ---
    # ("https://www.ou.nl/en/-/study-offers", 1),                    # Open Universiteit (NL)
    # ("https://www.uoc.edu/en/studies", 1),                         # Open University of Catalonia (ES)
    # ("https://www.unisa.ac.za/sites/corporate/default/Apply-for-admission/Undergraduate-qualifications", 1),
    # ("https://www.unisa.ac.za/sites/corporate/default/Apply-for-admission/Honours-degrees-&-postgraduate-diplomas", 1),
    # ("https://www.ignou.ac.in/ignou/aboutignou/school", 1),        # IGNOU (IN)
    # ("https://www.oum.edu.my/programmes/", 1),                     # Open University Malaysia
]

def write_etl_error_log(url, stage, exc, log_dt):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    os.makedirs("log", exist_ok=True)
    with open(f"log/etl_error_log_{log_dt}.txt", "a", encoding="utf-8") as f:
        f.write(f"[{ts}] stage={stage} url={url} error={type(exc).__name__}: {exc}\n")
        f.write(traceback.format_exc())
        f.write("\n")


def make_site_slug(url):
    parsed = urlparse(url)
    path = parsed.path.strip("/").replace("/", "__") or "root"
    return f"{parsed.netloc}__{path}"


def snapshot_csv_outputs(url, log_dt, src_dir="db/csv_output"):
    snapshot_dir = os.path.join("db", "csv_output_snapshots", f"{log_dt}__{make_site_slug(url)}")
    os.makedirs(snapshot_dir, exist_ok=True)

    for name in ("universities.csv", "degree_programs.csv", "tuition_patterns.csv", "program_tuition_map.csv"):
        src = os.path.join(src_dir, name)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(snapshot_dir, name))


async def run_etl():
    log_dt = datetime.now().strftime("%Y%m%d_%H%M%S")
    ts_start = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    os.makedirs("log", exist_ok=True)
    with open(f"log/crawl_log_{log_dt}.txt", "a", encoding="utf-8") as f:
        f.write(f"\n{'#'*60}\n")
        f.write(f"# ETL開始: {ts_start}  ({len(searchURLs)}サイト)\n")
        f.write(f"{'#'*60}\n\n")

    for url, crawl_depth in searchURLs:
        print(f"\nクローリング開始: {url} (depth={crawl_depth})")

        try:
            await crawl_main(url, crawl_depth, log_dt=log_dt)
        except Exception as e:
            if isinstance(e, HTTPError) and e.response.status_code == 404:
                print(f"[ETL WARNING] 404エラー: {url} をスキップします。")
                continue
            write_etl_error_log(url, "crawl", e, log_dt)
            print(f"[ETL ERROR] crawl 失敗: {url} ({e})")
            continue

        print("CSV生成開始...")
        try:
            json_to_csv_main()
            snapshot_csv_outputs(url, log_dt)
        except Exception as e:
            write_etl_error_log(url, "csv", e, log_dt)
            print(f"[ETL ERROR] CSV生成失敗: {url} ({e})")
            continue

        print("データベース保存開始...")
        try:
            db_saver_main()
        except Exception as e:
            write_etl_error_log(url, "db", e, log_dt)
            print(f"[ETL ERROR] DB保存失敗: {url} ({e})")
            continue

    ts_end = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(f"log/crawl_log_{log_dt}.txt", "a", encoding="utf-8") as f:
        f.write(f"{'#'*60}\n")
        f.write(f"# ETL完了: {ts_end}\n")
        f.write(f"{'#'*60}\n\n")

    print("\nETLパイプライン完了！")
    print(f"エラー詳細は log/etl_error_log_{log_dt}.txt を確認してください。")

if __name__ == "__main__":
    asyncio.run(run_etl())