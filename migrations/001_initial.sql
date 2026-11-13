CREATE TABLE IF NOT EXISTS schema_migration (version TEXT PRIMARY KEY, applied_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS source_batch (
 batch_id TEXT PRIMARY KEY, source_name TEXT NOT NULL, endpoint TEXT NOT NULL, requested_at TEXT NOT NULL,
 source_available_at TEXT, source_timestamp TEXT, received_at TEXT NOT NULL, request_id TEXT,
 source_version TEXT, coverage_json TEXT NOT NULL DEFAULT '{}', status TEXT NOT NULL,
 raw_uri TEXT NOT NULL, content_sha256 TEXT NOT NULL UNIQUE, item_count INTEGER,
 CHECK(status IN ('SUCCESS','PARTIAL','FAILED','STALE'))
);
CREATE TABLE IF NOT EXISTS security_master_snapshot (
 security_id TEXT NOT NULL, ticker TEXT NOT NULL, exchange TEXT, name TEXT, listed_date TEXT,
 is_st INTEGER, st_status TEXT NOT NULL DEFAULT 'UNVERIFIED', valid_from TEXT NOT NULL,
 snapshot_version TEXT NOT NULL, source_batch_id TEXT NOT NULL REFERENCES source_batch(batch_id),
 PRIMARY KEY(security_id, valid_from, snapshot_version)
);
CREATE TABLE IF NOT EXISTS trading_calendar (
 trade_date TEXT PRIMARY KEY, is_trading_day INTEGER NOT NULL, session TEXT, source_batch_id TEXT REFERENCES source_batch(batch_id)
);
CREATE TABLE IF NOT EXISTS daily_bar (
 security_id TEXT NOT NULL, trade_date TEXT NOT NULL, price_version TEXT NOT NULL,
 open REAL, high REAL, low REAL, close REAL, prev_close REAL, volume_shares REAL, turnover_cny REAL,
 source_batch_id TEXT NOT NULL REFERENCES source_batch(batch_id), PRIMARY KEY(security_id, trade_date, price_version)
);
CREATE TABLE IF NOT EXISTS intraday_bar (
 security_id TEXT NOT NULL, event_time TEXT NOT NULL, source_batch_id TEXT NOT NULL REFERENCES source_batch(batch_id),
 last_price REAL, volume_shares REAL, turnover_cny REAL, source_name TEXT NOT NULL, PRIMARY KEY(security_id,event_time,source_batch_id)
);
CREATE TABLE IF NOT EXISTS factor_value (
 factor_id TEXT NOT NULL, factor_version TEXT NOT NULL, security_id TEXT, decision_cutoff TEXT NOT NULL,
 raw_value_json TEXT, transformed_value_json TEXT, validity TEXT NOT NULL, missing_reason TEXT,
 coverage REAL, data_asof TEXT, source_batch_ids TEXT NOT NULL DEFAULT '[]', explanation TEXT,
 PRIMARY KEY(factor_id,factor_version,security_id,decision_cutoff)
);
CREATE TABLE IF NOT EXISTS strategy_version (strategy_version TEXT PRIMARY KEY, config_json TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS signal_snapshot (
 signal_id TEXT PRIMARY KEY, trade_date TEXT NOT NULL, decision_cutoff TEXT NOT NULL, published_at TEXT NOT NULL,
 strategy_version TEXT NOT NULL, factor_registry_version TEXT NOT NULL, data_status TEXT NOT NULL,
 data_status_reason TEXT, market_asof TEXT, source_batch_ids TEXT NOT NULL DEFAULT '[]', created_at TEXT NOT NULL,
 UNIQUE(trade_date,decision_cutoff,strategy_version,factor_registry_version)
);
CREATE TABLE IF NOT EXISTS signal_candidate (
 signal_id TEXT NOT NULL REFERENCES signal_snapshot(signal_id), security_id TEXT NOT NULL, rank INTEGER NOT NULL,
 score REAL, eligibility_status TEXT NOT NULL, strategy_ids TEXT NOT NULL DEFAULT '[]', evidence_json TEXT NOT NULL DEFAULT '[]',
 risks_json TEXT NOT NULL DEFAULT '[]', factor_refs TEXT NOT NULL DEFAULT '[]', PRIMARY KEY(signal_id,security_id)
);
CREATE TABLE IF NOT EXISTS job_run (
 job_run_id TEXT PRIMARY KEY, idempotency_key TEXT NOT NULL UNIQUE, job_name TEXT NOT NULL, status TEXT NOT NULL,
 started_at TEXT NOT NULL, finished_at TEXT, coverage_json TEXT NOT NULL DEFAULT '{}', error_code TEXT, error_message TEXT
);
CREATE INDEX IF NOT EXISTS ix_source_batch_received ON source_batch(received_at);
CREATE INDEX IF NOT EXISTS ix_calendar_trading ON trading_calendar(is_trading_day, trade_date);
