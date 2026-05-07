#例外にするべきもの
# DB接続失敗
# SQL実行エラー
# 入力値不正
#欠損値はnullで返す
#必要レコードだけselectする
#このAPIの権限はselectだけでいい
#DBの権限はPostgreSQLのロールで決定されるため、DB_configに注意

import os
from typing import Optional
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
import psycopg2
from dotenv import load_dotenv

load_dotenv()

_REQUIRED_ENV = ["DB_HOST", "DB_NAME", "DB_READUSER", "DB_READPASSWORD", "DB_PORT"]
_missing = [k for k in _REQUIRED_ENV if not os.getenv(k)]
if _missing:
    raise EnvironmentError(f".envに必要な環境変数が設定されていません: {_missing}")

DB_CONFIG = {
    "host": os.getenv("DB_HOST"),
    "dbname": os.getenv("DB_NAME"),
    "user": os.getenv("DB_READUSER"),
    "password": os.getenv("DB_READPASSWORD"),
    "port": int(os.getenv("DB_PORT")),
}

app = FastAPI(title="学位検索API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

def get_connection():
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        return conn
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database connection failed: {str(e)}")

def close_connection(conn):
    try:
        conn.close()
    except Exception as e:
        print(f"Failed to close connection: {str(e)}")

@app.get("/search")
def search_programs(
    keyword: Optional[str] = None,
    country: Optional[str] = None,
    degree: Optional[str] = None,
    category: Optional[str] = None,
    is_online: Optional[bool] = None,
    tuition_type: Optional[str] = None,
    fixed_only: bool = Query(False),
    non_fixed_only: bool = Query(False),
    price_min: Optional[int] = Query(None, ge=0),
    price_max: Optional[int] = Query(None, ge=0),
    currency: Optional[str] = None,
    sort_by: str = Query("last_seen", pattern="^(last_seen|amount|normalized_monthly_amount)$"),
    sort_order: str = Query("desc", pattern="^(asc|desc)$"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0)
):
    if fixed_only and non_fixed_only:
        raise HTTPException(
            status_code=400,
            detail="fixed_only and non_fixed_only cannot both be true"
        )

    if price_min is not None and price_max is not None:
        if price_min > price_max:
            raise HTTPException(
                status_code=400,
                detail="price_min must be <= price_max"
            )

    query = """
        SELECT
            dp.program_name,
            u.country,
            u.name AS university_name,
            tp.degree_level,
            dp.course_type,
            tp.amount,
            tp.currency,
            tp.tuition_type,
            tp.normalized_monthly_amount,
            tp.normalization_note,
            dp.is_online,
            dp.last_seen
        FROM degree_programs dp
        JOIN universities u ON dp.university_id = u.id
        LEFT JOIN program_tuition_map ptm ON ptm.degree_program_id = dp.id
        LEFT JOIN tuition_patterns tp ON ptm.tuition_pattern_id = tp.id
        WHERE 1=1
    """

    params = []
    if keyword:
        query += """
            AND (
                dp.program_name ILIKE %s
                OR COALESCE(tp.degree_level, '') ILIKE %s
                OR dp.course_type ILIKE %s
            )
        """
        word = f"%{keyword}%"
        params.extend([word, word, word])
    if country:
        query += " AND u.country = %s"
        params.append(country)
    if degree:
        query += " AND tp.degree_level = %s"
        params.append(degree)
    if category:
        query += " AND dp.course_type = %s"
        params.append(category)
    if is_online is not None:
        query += " AND dp.is_online = %s"
        params.append(is_online)
    if tuition_type:
        query += " AND tp.tuition_type = %s"
        params.append(tuition_type)
    if fixed_only:
        query += " AND tp.tuition_type IN (%s, %s, %s)"
        params.extend(["fixed_year", "fixed_month", "fixed_semester"])
    if non_fixed_only:
        query += " AND tp.tuition_type NOT IN (%s, %s, %s)"
        params.extend(["fixed_year", "fixed_month", "fixed_semester"])
    if currency:
        query += " AND tp.currency = %s"
        params.append(currency)
    if price_min is not None:
        query += " AND tp.amount >= %s"
        params.append(price_min)
    if price_max is not None:
        query += " AND tp.amount <= %s"
        params.append(price_max)

    sort_columns = {
        "last_seen": "dp.last_seen",
        "amount": "tp.amount",
        "normalized_monthly_amount": "tp.normalized_monthly_amount",
    }
    order_col = sort_columns.get(sort_by, "dp.last_seen")
    order_dir = "ASC" if sort_order == "asc" else "DESC"
    query += f" ORDER BY {order_col} {order_dir} NULLS LAST LIMIT %s OFFSET %s"
    params.extend([limit, offset])

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(query, tuple(params))
            results = cur.fetchall()

            return [
                {
                    "program_name": row[0],
                    "country": row[1],
                    "university_name": row[2],
                    "degree_level": row[3],
                    "course_type": row[4],
                    "amount": row[5],
                    "currency": row[6],
                    "tuition_type": row[7],
                    "normalized_monthly_amount": float(row[8]) if row[8] is not None else None,
                    "normalization_note": row[9],
                    "is_online": row[10],
                    "last_seen": row[11].isoformat() if row[11] else None
                }
                for row in results
            ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"SQL execution failed: {str(e)}")
    finally:
        close_connection(conn)


@app.get("/countries")
def get_countries():
    """国一覧（フロントエンドのドロップダウン用）"""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT country FROM universities WHERE country IS NOT NULL ORDER BY country"
            )
            return [row[0] for row in cur.fetchall()]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"SQL execution failed: {str(e)}")
    finally:
        close_connection(conn)


@app.get("/degree-levels")
def get_degree_levels():
    """学位レベル一覧（フロントエンドのドロップダウン用）"""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT degree_level FROM tuition_patterns WHERE degree_level IS NOT NULL ORDER BY degree_level"
            )
            return [row[0] for row in cur.fetchall()]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"SQL execution failed: {str(e)}")
    finally:
        close_connection(conn)


@app.get("/currencies")
def get_currencies():
    """通貨一覧（フロントエンドのドロップダウン用）"""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT currency FROM tuition_patterns WHERE currency IS NOT NULL ORDER BY currency"
            )
            return [row[0] for row in cur.fetchall()]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"SQL execution failed: {str(e)}")
    finally:
        close_connection(conn)


@app.get("/tuition-types")
def get_tuition_types():
    """料金タイプ一覧（フロントエンドのドロップダウン用）"""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT tuition_type FROM tuition_patterns WHERE tuition_type IS NOT NULL ORDER BY tuition_type"
            )
            return [row[0] for row in cur.fetchall()]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"SQL execution failed: {str(e)}")
    finally:
        close_connection(conn)