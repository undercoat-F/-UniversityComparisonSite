/*
URLリスト編集用SQL
追加
INSERT INTO seed_urls (country, domain, root_url, depth, enabled) VALUES (...);

更新
UPDATE seed_urls SET depth=..., enabled=... WHERE domain=... AND root_url=...;

無効化
UPDATE seed_urls SET enabled=0 WHERE ...;

確認
SELECT id, domain, root_url, depth, enabled FROM seed_urls ORDER BY id
*/


-- 集計用　直近14日サマリー（件数、平均、分位、最大）
WITH recent AS (
SELECT error_count
FROM seed_observe_results
WHERE created_at >= now() - interval '14 days'
)
SELECT
count(*) AS n,
avg(error_count)::numeric(10,2) AS avg_err,
percentile_cont(0.5) WITHIN GROUP (ORDER BY error_count) AS p50,
percentile_cont(0.75) WITHIN GROUP (ORDER BY error_count) AS p75,
percentile_cont(0.9) WITHIN GROUP (ORDER BY error_count) AS p90,
max(error_count) AS max_err
FROM recent;

-- 集計用　直近14日ヒストグラム
SELECT
error_count,
count(*) AS row_count
FROM seed_observe_results
WHERE created_at >= now() - interval '14 days'
GROUP BY error_count
ORDER BY error_count;