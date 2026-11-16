"""Machine-readable data and runtime quality report."""
from __future__ import annotations
from datetime import datetime,timezone

def _count(conn, table): return conn.execute(f"select count(*) from {table}").fetchone()[0]
def build_report(store, *, now=None, max_quote_age_seconds=900):
    now=now or datetime.now(timezone.utc); counts={}
    for table in ('source_batch','security_master_snapshot','trading_calendar','daily_bar','quote_snapshot','index_master','index_membership_snapshot','factor_value','signal_snapshot','signal_candidate','signal_candidate_evaluation','job_run','shadow_observation'):
        try: counts[table]=_count(store.conn,table)
        except Exception: counts[table]=None
    reasons=[]; latest=store.conn.execute("select event_time from quote_snapshot order by event_time desc limit 1").fetchone()
    latest_event_row=store.conn.execute("select max(event_time) from quote_snapshot").fetchone(); latest_event=latest_event_row[0] if latest_event_row else None
    latest_master_row=store.conn.execute("select max(valid_from) from security_master_snapshot").fetchone(); latest_master=latest_master_row[0] if latest_master_row else None
    quote_ids={r[0] for r in store.conn.execute("select distinct security_id from quote_snapshot where event_time=?",(latest_event,))} if latest_event else set()
    universe_ids={r[0] for r in store.conn.execute("select distinct security_id from security_master_snapshot where valid_from=?",(latest_master,))} if latest_master else set()
    universe_coverage=(len(quote_ids & universe_ids)/len(universe_ids)) if universe_ids else 0.0
    if quote_ids and universe_coverage < 1.0: reasons.append('UNIVERSE_SNAPSHOT_MISMATCH')
    quote_age=None
    if not latest: reasons.append('NO_QUOTE_SNAPSHOT')
    else:
        try: quote_age=(now-datetime.fromisoformat(latest[0].replace('Z','+00:00'))).total_seconds()
        except (TypeError,ValueError): reasons.append('INVALID_QUOTE_TIMESTAMP')
        if quote_age is not None and quote_age>max_quote_age_seconds: reasons.append('STALE_QUOTE_SNAPSHOT')
    dup=store.conn.execute("select count(*) from (select factor_id,factor_version,security_id,decision_cutoff,count(*) n from factor_value group by 1,2,3,4 having n>1)").fetchone()[0]
    if dup: reasons.append('DUPLICATE_FACTOR_KEYS')
    if counts.get('daily_bar') == 0: reasons.append('DAILY_HISTORY_EMPTY')
    master_count=store.conn.execute("select count(distinct security_id) from security_master_snapshot where valid_from=(select max(valid_from) from security_master_snapshot)").fetchone()[0]
    daily_count=store.conn.execute("select count(distinct security_id) from daily_bar").fetchone()[0]
    history_coverage=daily_count/master_count if master_count else 0.0
    if master_count and history_coverage < 0.9: reasons.append('DAILY_HISTORY_COVERAGE_LOW')
    failed=store.conn.execute("select count(*) from job_run where status in ('FAILED','BLOCKED')").fetchone()[0]
    return {'status':'BLOCKED' if reasons else 'VALID','reasons':reasons,'counts':counts,'latest_quote_age_seconds':quote_age,'failed_or_blocked_jobs':failed,'universe_coverage':universe_coverage,'daily_history_coverage':history_coverage,'checked_at':now.isoformat()}
