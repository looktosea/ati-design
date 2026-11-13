CREATE TABLE IF NOT EXISTS index_daily_bar (
 index_id TEXT NOT NULL, trade_date TEXT NOT NULL, price_version TEXT NOT NULL,
 open REAL, high REAL, low REAL, close REAL, prev_close REAL, turnover_cny REAL,
 source_batch_id TEXT NOT NULL REFERENCES source_batch(batch_id),
 PRIMARY KEY(index_id,trade_date,price_version)
);
CREATE TABLE IF NOT EXISTS shadow_observation (
 observation_id TEXT PRIMARY KEY, source_name TEXT NOT NULL, endpoint TEXT NOT NULL,
 security_id TEXT, event_time TEXT, received_at TEXT NOT NULL, status TEXT NOT NULL,
 raw_json TEXT NOT NULL, source_batch_id TEXT REFERENCES source_batch(batch_id)
);
