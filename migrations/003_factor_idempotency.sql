DELETE FROM factor_value
WHERE rowid NOT IN (
  SELECT MAX(rowid) FROM factor_value
  GROUP BY factor_id, factor_version, COALESCE(security_id, ''), decision_cutoff
);
UPDATE factor_value SET security_id = '' WHERE security_id IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ux_factor_value_key
 ON factor_value(factor_id, factor_version, security_id, decision_cutoff);
