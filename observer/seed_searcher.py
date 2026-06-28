from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse

import psycopg2
from dotenv import load_dotenv

from observer.observe_supervisor import ObserveStackItem

import asyncio
import requests
import httpx

load_dotenv(encoding="utf-8-sig")

"""
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
"""


class SearchAPI:
	"""検索APIの呼び出しを抽象化するクラス"""
	def __init__(self, api_key: str | None = None):
		self.api_key = api_key or os.getenv("SEARCH_API_KEY")
		if not self.api_key:
			raise ValueError("SEARCH_API_KEY が設定されていません。")

	def search(self, request: SearchRequest) -> dict:
		# ここに実際の検索API呼び出しを実装する予定。
		# 現在はダミーのレスポンスを返す。
		return {
			"source_url": request.source_url,
			"universities": request.university_names,
			"content_type": request.content_type,
			"status": "success",
			"results": [],
		}
	
	class BraveAPI:
		headers = {
			 "User-Agent": (
        	"Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        	"AppleWebKit/537.36 (KHTML, like Gecko) "
        	"Chrome/124.0.0.0 Safari/537.36"
    	)}
		API_KEY: str = os.getenv("BRAVE_API_KEY")
		response_format: str = "json"
	
	def get_brave_search_results(self, query: str, num_results: int = 10) -> dict:
		if not self.API_KEY:
			raise ValueError("BRAVE_API_KEY が設定されていません。")
		
		url = f"https://api.search.brave.com/res/v1/web/search"
		params = {
			"q": query,
			"num": num_results,
			"format": self.response_format,
		}
		headers = self.headers.copy()
		headers["Authorization"] = f"Bearer {self.API_KEY}"
		
		try :
			#httpxでリクエストしたのち、失敗すればrequestsでリトライする
			response = httpx.get(url, params=params, headers=headers, timeout=10)
			response.raise_for_status()
			return response.json()
		except httpx.RequestError as e:
			print(f"[WARN] Brave API request failed: {e}. Retrying with requests library...")
			try:
				response = requests.get(url, params=params, headers=headers, timeout=10)
				response.raise_for_status()
				return response.json()
			except requests.RequestException as e:
				print(f"[ERROR] Brave API request failed with requests library: {e}")
				raise
			
		except requests.RequestException as e:

		
		response.raise_for_status()
		return response.json()


@dataclass
class SearchRequest:
	source_url: str
	university_names: list[str]
	content_type: str


def _get_db_params() -> dict:
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


def _extract_domain_and_root(url: str) -> tuple[str, str]:
	"""URL から domain と root_url を抽出"""
	parsed = urlparse(url)
	domain = parsed.netloc
	root_url = f"{parsed.scheme}://{parsed.netloc}"
	return domain, root_url


def _is_duplicate(domain: str, root_url: str) -> bool:
	"""(domain, root_url) が既存の seed_urls に存在するかチェック"""
	try:
		db_params = _get_db_params()
		with psycopg2.connect(**db_params) as conn:
			cursor = conn.cursor()
			cursor.execute(
				"SELECT 1 FROM seed_urls WHERE domain = %s AND root_url = %s",
				(domain, root_url)
			)
			return cursor.fetchone() is not None
	except psycopg2.Error as e:
		print(f"[WARN] seed_urls チェック失敗: {e}")
		return False


def build_search_request(item: ObserveStackItem) -> SearchRequest:
	return SearchRequest(
		source_url=item.source_url,
		university_names=list(item.university_names),
		content_type=item.page_analysis.content_type.value,
	)


def handle_observe_item(item: ObserveStackItem) -> None:
	# 重複判定
	domain, root_url = _extract_domain_and_root(item.source_url)
	if _is_duplicate(domain, root_url):
		print(
			"[OBSERVE_SEARCHER] "
			f"SKIPPED (duplicate) source={item.source_url} "
			f"domain={domain}"
		)
		return
	
	request = build_search_request(item)
	# ここに検索API呼び出しを追加予定。
	print(
		"[OBSERVE_SEARCHER] "
		f"source={request.source_url} "
		f"universities={len(request.university_names)} "
		f"content_type={request.content_type}"
	)
