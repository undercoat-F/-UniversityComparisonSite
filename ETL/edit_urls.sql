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