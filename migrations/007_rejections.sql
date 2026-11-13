CREATE TABLE IF NOT EXISTS signal_rejection (
 signal_id TEXT NOT NULL REFERENCES signal_snapshot(signal_id), security_id TEXT NOT NULL,
 reason_code TEXT NOT NULL, factor_refs TEXT NOT NULL DEFAULT '[]', details_json TEXT NOT NULL DEFAULT '{}',
 created_at TEXT NOT NULL, PRIMARY KEY(signal_id,security_id)
);
