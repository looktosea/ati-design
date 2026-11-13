CREATE TABLE IF NOT EXISTS quote_snapshot (
 security_id TEXT NOT NULL, event_time TEXT NOT NULL, source_batch_id TEXT NOT NULL REFERENCES source_batch(batch_id),
 ticker TEXT, exchange TEXT, name TEXT, last_price REAL, prev_close REAL, open REAL, high REAL, low REAL,
 volume_shares REAL, turnover_cny REAL, price_change_pct REAL, trade_status TEXT, is_st INTEGER,
 status TEXT NOT NULL DEFAULT 'VALID', source_name TEXT NOT NULL, raw_ref TEXT,
 PRIMARY KEY(security_id,event_time,source_batch_id)
);
CREATE INDEX IF NOT EXISTS ix_quote_snapshot_event_time ON quote_snapshot(event_time);
CREATE TABLE IF NOT EXISTS signal_evaluation (
 signal_id TEXT NOT NULL REFERENCES signal_snapshot(signal_id), evaluation_policy_version TEXT NOT NULL,
 horizon_days INTEGER NOT NULL, reference_price REAL, reference_time TEXT, status TEXT NOT NULL,
 gross_return REAL, net_reference_return REAL, max_adverse_move REAL, endpoint_trade_date TEXT,
 unresolved_reason TEXT, created_at TEXT NOT NULL,
 PRIMARY KEY(signal_id,evaluation_policy_version,horizon_days)
);
CREATE TABLE IF NOT EXISTS factor_run (
 factor_run_id TEXT PRIMARY KEY, decision_cutoff TEXT NOT NULL, factor_registry_version TEXT NOT NULL,
 source_batch_ids TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL,
 UNIQUE(decision_cutoff,factor_registry_version)
);
