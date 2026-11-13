CREATE TABLE IF NOT EXISTS signal_candidate_evaluation (
 signal_id TEXT NOT NULL REFERENCES signal_snapshot(signal_id), security_id TEXT NOT NULL,
 evaluation_policy_version TEXT NOT NULL, horizon_days INTEGER NOT NULL,
 reference_price REAL, reference_time TEXT, status TEXT NOT NULL,
 gross_return REAL, net_reference_return REAL, max_adverse_move REAL, endpoint_trade_date TEXT,
 unresolved_reason TEXT, created_at TEXT NOT NULL, evaluated_at TEXT,
 PRIMARY KEY(signal_id,security_id,evaluation_policy_version,horizon_days)
);
CREATE INDEX IF NOT EXISTS ix_candidate_eval_status ON signal_candidate_evaluation(status,endpoint_trade_date);
