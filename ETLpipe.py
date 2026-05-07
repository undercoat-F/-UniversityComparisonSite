from crawler.crawlAndSaver import main as crawl_main
from db.jsontocsv import main as json_to_csv_main
from db.db_saver import main as db_saver_main
import asyncio
import os
import shutil
from datetime import datetime
import traceback
from urllib.parse import urlparse


# (URL, depth) のタプル形式。depth省略時はcrawlAndSaver.pyのデフォルト値(depth=2)が使われる
searchURLs = [
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