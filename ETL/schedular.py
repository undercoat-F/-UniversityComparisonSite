import asyncio
import ast
import json
import os
import psycopg2
import shutil
import time
from datetime import datetime
import traceback
from urllib.parse import urlparse

from dotenv import load_dotenv

from ETL.dispatcher import run_dispatcher
from crawler.metrics import analyze_degree_duplicates

load_dotenv(encoding="utf-8-sig")


# (URL, depth) tuple list
URL_LIST_PATH = os.path.join("ETL", "URLs.txt")


def get_db_params():
	"""PostgreSQL 接続パラメータを .env から取得"""
	required_keys = ["DB_HOST", "DB_NAME", "DB_USER", "DB_PASSWORD", "DB_PORT"]
	missing = [k for k in required_keys if not os.getenv(k)]
	if missing:
		raise EnvironmentError(f".env に必須環境変数が未設定: {missing}")
	
	return {
		"host": os.getenv("DB_HOST"),
		"dbname": os.getenv("DB_NAME"),
		"user": os.getenv("DB_USER"),
		"password": os.getenv("DB_PASSWORD"),
		"port": int(os.getenv("DB_PORT", "5432")),
	}


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


def load_targets_from_db():
	"""PostgreSQL から enabled=1 の seed_urls を読み込む"""
	query = """
		SELECT root_url, depth
		FROM seed_urls
		WHERE enabled = 1
		ORDER BY id
	"""

	try:
		db_params = get_db_params()
		with psycopg2.connect(**db_params) as conn:
			cursor = conn.cursor()
			cursor.execute(query)
			rows = cursor.fetchall()
		return [(str(url), int(depth)) for url, depth in rows]
	except psycopg2.Error as e:
		print(f"[WARN] seed_urls 読み込み失敗: {e}")
		return []


def load_targets_from_txt(path=URL_LIST_PATH):
    if not os.path.exists(path):
        return []

    with open(path, "r", encoding="utf-8") as f:
        targets = []
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if not line.startswith("("):
                continue

            tuple_expr = line[:-1] if line.endswith(",") else line
            try:
                item = ast.literal_eval(tuple_expr)
            except Exception:
                continue

            if isinstance(item, tuple) and len(item) == 2:
                targets.append((str(item[0]), int(item[1])))
    return targets


def load_targets():
    targets = load_targets_from_db()
    if targets:
        return targets
    return load_targets_from_txt()


def write_extraction_logs(site_states, log_dt):
    os.makedirs("log", exist_ok=True)
    jsonl_path = os.path.join("log", f"extracted_records_{log_dt}.jsonl")
    summary_path = os.path.join("log", f"extracted_summary_{log_dt}.txt")

    total_records = 0
    total_degrees = 0
    with open(jsonl_path, "w", encoding="utf-8") as jf:
        for site in site_states:
            for record in site.extracted_records:
                total_records += 1
                degree_count = len(record.get("degrees", []))
                total_degrees += degree_count
                payload = {
                    "domain": site.domain,
                    "url": record.get("url"),
                    "title": record.get("title"),
                    "timestamp": record.get("timestamp"),
                    "country": record.get("country"),
                    "degree_count": degree_count,
                    "degrees": record.get("degrees", []),
                }
                jf.write(json.dumps(payload, ensure_ascii=False) + "\n")

    with open(summary_path, "w", encoding="utf-8") as sf:
        sf.write(f"records={total_records}\n")
        sf.write(f"degrees={total_degrees}\n")
        for site in site_states:
            sf.write(
                f"domain={site.domain} records={len(site.extracted_records)} "
                f"success={site.success_count} errors={site.error_count} "
                f"fallback={site.fallback_count} sitemap_candidates={len(site.sitemap_candidates)}\n"
            )

    return jsonl_path, summary_path, total_records, total_degrees


async def run_etl():
    targets = load_targets()
    log_dt = datetime.now().strftime("%Y%m%d_%H%M%S")
    ts_start = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[SCHEDULER] ETL start targets={len(targets)}", flush=True)
    os.makedirs("log", exist_ok=True)
    with open(f"log/crawl_log_{log_dt}.txt", "a", encoding="utf-8") as f:
        f.write(f"\n{'#'*10}\n")
        f.write(f"# ETL start: {ts_start} ({len(targets)} sites)\n")
        f.write(f"{'#'*10}\n\n")

    try:
        site_states = await run_dispatcher(targets)
    except Exception as e:
        write_etl_error_log("ALL", "dispatcher", e, log_dt)
        raise

    for site in site_states:
        print(
            "[SCHEDULER] "
            f"domain={site.domain} success={site.success_count} errors={site.error_count} "
            f"fallback={site.fallback_count} visited={len(site.visited)} "
            f"sitemap_candidates={len(site.sitemap_candidates)}"
        )
        if site.error_count:
            for error_msg in site.errors:
                write_etl_error_log(site.domain, "crawl", RuntimeError(error_msg), log_dt)

    jsonl_path, summary_path, total_records, total_degrees = write_extraction_logs(site_states, log_dt)

    ts_end = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(f"log/crawl_log_{log_dt}.txt", "a", encoding="utf-8") as f:
        f.write(f"{'#'*10}\n")
        f.write(f"# ETL finished: {ts_end}\n")
        f.write(f"# extracted records: {total_records} / extracted degrees: {total_degrees}\n")
        f.write(f"# extracted JSONL: {jsonl_path}\n")
        f.write(f"# extracted summary: {summary_path}\n")
        f.write(f"{'#'*10}\n\n")

    print("\nScheduler run completed")
    print(f"Error details: log/etl_error_log_{log_dt}.txt")
    print(f"Extracted JSONL: {jsonl_path}")
    print(f"Extracted summary: {summary_path}")

if __name__ == "__main__":
    asyncio.run(run_etl())
