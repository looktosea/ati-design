CREATE TABLE IF NOT EXISTS index_master (
 index_id TEXT PRIMARY KEY, index_code TEXT NOT NULL, name TEXT, kind TEXT NOT NULL,
 exchange TEXT, valid_from TEXT NOT NULL, valid_to TEXT, snapshot_version TEXT NOT NULL,
 source_batch_id TEXT NOT NULL REFERENCES source_batch(batch_id)
);
CREATE TABLE IF NOT EXISTS index_membership_snapshot (
 index_id TEXT NOT NULL, security_id TEXT NOT NULL, valid_from TEXT NOT NULL, valid_to TEXT,
 snapshot_version TEXT NOT NULL, source_batch_id TEXT NOT NULL REFERENCES source_batch(batch_id),
 PRIMARY KEY(index_id,security_id,valid_from,snapshot_version)
);
CREATE TABLE IF NOT EXISTS index_quote_snapshot (
 index_id TEXT NOT NULL, event_time TEXT NOT NULL, source_batch_id TEXT NOT NULL REFERENCES source_batch(batch_id),
 last_price REAL, prev_close REAL, price_change_pct REAL, turnover_cny REAL, status TEXT NOT NULL DEFAULT 'VALID',
 PRIMARY KEY(index_id,event_time,source_batch_id)
);
CREATE TABLE IF NOT EXISTS limit_stat_snapshot (
 trade_date TEXT NOT NULL, event_time TEXT, source_batch_id TEXT NOT NULL REFERENCES source_batch(batch_id),
 up_count INTEGER, down_count INTEGER, break_count INTEGER, eligible_count INTEGER,
 status TEXT NOT NULL DEFAULT 'VALID', raw_json TEXT NOT NULL DEFAULT '{}',
 PRIMARY KEY(trade_date,event_time,source_batch_id)
);
CREATE INDEX IF NOT EXISTS ix_membership_security ON index_membership_snapshot(security_id,valid_from);
