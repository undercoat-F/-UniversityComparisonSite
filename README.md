# -UniversityComparisonSite

## Docker

このリポジトリは API と静的ページ配信用途に絞ってコンテナ化できます。

Dockerfile は複数持てます。このリポジトリでは用途ごとに分けるのが自然です。

- Dockerfile.api: API 配布用
- Dockerfile.etl: ETL 一括実行用
- Dockerfile.observe: observe パイプライン用

ローカルでまとめて扱うために [docker-compose.yml](docker-compose.yml) も用意しています。

### 含めるもの
- search/
- db/
- webpage/
- requirements.txt

### 含めないもの
- .env
- .venv などの仮想環境
- .VSCodeCounter
- log/
- docs/
- tests/
- crawler/、ETL/、observer/ など API 実行に不要な補助ディレクトリ

### build

```bash
docker build -f Dockerfile.api -t university-comparison-site .
```

ETL 用:

```bash
docker build -f Dockerfile.etl -t university-comparison-etl .
```

observe 用:

```bash
docker build -f Dockerfile.observe -t university-comparison-observe .
```

compose でまとめて build:

```bash
docker compose build
```

### run

`.env` はイメージに含めず、起動時に渡します。

```bash
docker run --rm -p 8000:8000 --env-file .env university-comparison-site
```

ETL 用:

```bash
docker run --rm --env-file .env university-comparison-etl
```

ETL は起動時に queue log 系テーブル名も読みます。少なくとも以下も .env に必要です。

- SEED_URLS_TABLE
- UNIVERSITIES_TABLE
- CRAWL_RUNS_TABLE
- CRAWL_QUEUE_STATE_TABLE
- CRAWL_ATTEMPTS_TABLE
- CRAWL_EDGES_TABLE
- CRAWL_FAILURES_TABLE
- CRAWL_TAG_KEYWORD_HITS_TABLE
- CRAWL_DOMAIN_TAG_SCORES_TABLE
- CRAWL_TAG_CLASS_COUNTS_TABLE
- CRAWL_DOMAIN_CLASS_COUNTS_TABLE

observe 用:

```bash
docker run --rm --env-file .env university-comparison-observe
```

compose で API 起動:

```bash
docker compose up api
```

compose で ETL 実行:

```bash
docker compose --profile etl run --rm etl
```

compose で observe 実行:

```bash
docker compose --profile observe run --rm observe
```

実際の `.env` が未整備でも、サンプルを使って compose 定義だけ確認できます。

```bash
$env:COMPOSE_ENV_FILE='.env.example'
docker compose config
```

Docker の `--env-file` は `KEY=value` 形式を厳密に要求します。`KEY = value` のように `=` の前後へ空白を入れると読み込めません。

ブラウザ確認先:

- http://localhost:8000/
- http://localhost:8000/health

### 必須環境変数

開発 DB を使う場合:

- DB_HOST
- DB_NAME
- DB_READUSER
- DB_READPASSWORD
- DB_PORT
- UNIVERSITIES_TABLE
- DEGREE_PROGRAMS_TABLE
- TUITION_PATTERNS_TABLE
- PROGRAM_TUITION_MAP_TABLE

本番系 DB を使う場合:

- PARENT_DB_HOST
- PARENT_DB_NAME
- PARENT_DB_USER
- PARENT_DB_PASSWORD
- PARENT_DB_PORT
- UNIVERSITIES_TABLE
- DEGREE_PROGRAMS_TABLE
- TUITION_PATTERNS_TABLE
- PROGRAM_TUITION_MAP_TABLE

テーブル変数の既存値例:

```env
UNIVERSITIES_TABLE=public.universities
DEGREE_PROGRAMS_TABLE=public.degree_programs
TUITION_PATTERNS_TABLE=public.tuition_patterns
PROGRAM_TUITION_MAP_TABLE=public.program_tuition_map
```

observe 用では追加で以下も必要です。

```env
SEED_URLS_TABLE=observer.seed_urls
SEED_OBSERVE_RUNS_TABLE=observer.seed_observe_runs
SEED_OBSERVE_RESULTS_TABLE=observer.seed_observe_results
SEED_SEARCH_RUNS_TABLE=observer.seed_search_runs
```

ETL 全体を AWS に載せる場合は、1 イメージに全部押し込むより、役割ごとに分ける方が運用しやすいです。

- API: ECS / App Runner / Fargate 常駐
- ETL: ECS RunTask か AWS Batch で都度実行
- observe: ECS RunTask か EventBridge 定期実行

この分け方なら、同じリポジトリに複数 Dockerfile を置いたまま運用できます。