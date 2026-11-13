"""L1 daily/quote factor and immutable signal snapshot pipeline."""
from __future__ import annotations
import hashlib, json
from datetime import datetime, timezone
from .factors import build_rejections, compute_daily_factors, compute_limit_factor, compute_market_daily_factors, compute_sector_factors, compute_snapshot_factors, rank_candidates

REGISTRY_VERSION="0.1.0"
STRATEGY_VERSION="baseline_daily_v0"
EVALUATION_POLICY_VERSION="daily-close-v0.1"

def _parse_dt(value):
    if not value: return None
    return datetime.fromisoformat(str(value).replace("Z","+00:00"))

def _signal_id(trade_date, cutoff, strategy, registry):
    raw=f"{trade_date}|{cutoff}|{strategy}|{registry}".encode()
    return "sig-"+hashlib.sha256(raw).hexdigest()[:24]

def run_l1(store, *, trade_date=None, decision_cutoff=None, strategy_version=STRATEGY_VERSION, registry_version=REGISTRY_VERSION, max_candidates=5, snapshot_status=None):
    """Calculate the currently supported L1 factors and write one idempotent signal.

    The function intentionally emits NO_CANDIDATE when daily history is not yet
    available; it never ranks a quote-only row as if it had trend history.
    """
    row=store.conn.execute("select event_time from quote_snapshot order by event_time desc limit 1").fetchone()
    if not row:
        now=datetime.now(timezone.utc); cutoff=(decision_cutoff or now.isoformat()); trade_date=trade_date or cutoff[:10]
        signal={"signal_id":_signal_id(trade_date,cutoff,strategy_version,registry_version),"trade_date":trade_date,"decision_cutoff":cutoff,"published_at":now.isoformat(),"strategy_version":strategy_version,"factor_registry_version":registry_version,"data_status":"BLOCKED","data_status_reason":"NO_MARKET_SNAPSHOT","source_batch_ids":[]}
        store.insert_signal(signal); _pending(store,signal["signal_id"]); return {"signal":signal,"candidates":[]}
    asof=_parse_dt(row[0]); cutoff=decision_cutoff or row[0]; trade_date=trade_date or (asof.date().isoformat() if asof else cutoff[:10])
    batch_rows=store.conn.execute("select distinct source_batch_id from quote_snapshot where event_time=(select max(event_time) from quote_snapshot)").fetchall(); batch_ids=[r[0] for r in batch_rows]
    quotes=[dict(r) for r in store.conn.execute("select * from quote_snapshot where event_time=(select max(event_time) from quote_snapshot)")]
    master_time=store.conn.execute("select max(valid_from) from security_master_snapshot").fetchone()[0]
    master={r[0]:dict(r) for r in store.conn.execute("select security_id,name,is_st from security_master_snapshot where valid_from=?",(master_time,))} if master_time else {}
    for quote in quotes:
        identity=master.get(quote["security_id"],{}); quote["name"]=identity.get("name"); quote["is_st"]=identity.get("is_st")
    calendar=store.conn.execute("select is_trading_day from trading_calendar where trade_date=?",(trade_date,)).fetchone()
    snapshot_gate=store.conn.execute("select status,item_count,source_timestamp from source_batch where batch_id=?",(batch_ids[-1],)).fetchone() if batch_ids else None
    factors=compute_snapshot_factors(quotes,cutoff,batch_ids,data_asof=row[0])
    history_by_security={}; history_batch_ids=set(batch_ids)
    for q in quotes:
        history=[dict(x) for x in store.conn.execute("select trade_date,open,high,low,close,prev_close,volume_shares,turnover_cny,source_batch_id from daily_bar where security_id=? order by trade_date",(q["security_id"],))]
        history_by_security[q["security_id"]]=history
        history_batch_ids.update(x["source_batch_id"] for x in history if x.get("source_batch_id"))
    history_sources=sorted(history_batch_ids)
    for q in quotes:
        factors.extend(compute_daily_factors(q["security_id"],history_by_security[q["security_id"]],q,cutoff,history_sources,registry_version))
    factors.append(compute_market_daily_factors(quotes,history_by_security,cutoff,history_sources,registry_version,row[0]))
    memberships_by_index={}; membership_batch_ids=set(history_sources)
    for r in store.conn.execute("select index_id,security_id,source_batch_id from index_membership_snapshot where valid_from=(select max(valid_from) from index_membership_snapshot)"):
        memberships_by_index.setdefault(r[0],set()).add(r[1]); membership_batch_ids.add(r[2])
    index_histories={}
    sector_values=compute_sector_factors(quotes,history_by_security,memberships_by_index,index_histories,cutoff,sorted(membership_batch_ids),registry_version,row[0])
    factors.extend(sector_values)
    limit_row=store.conn.execute("select raw_json,event_time,source_batch_id from limit_stat_snapshot where trade_date=? order by event_time desc limit 1",(trade_date,)).fetchone()
    if limit_row:
        factors.append(compute_limit_factor(json.loads(limit_row[0]),cutoff,[limit_row[2]],registry_version,limit_row[1]))
    else:
        factors.append(compute_limit_factor(None,cutoff,batch_ids,registry_version,row[0]))
    store.insert_factor_values(factors)
    factor_run_id = _signal_id(trade_date, cutoff, "factor-run", registry_version)
    store.conn.execute("INSERT OR REPLACE INTO factor_run(factor_run_id,decision_cutoff,factor_registry_version,source_batch_ids,status,created_at) VALUES (?,?,?,?,?,?)", (factor_run_id, cutoff, registry_version, json.dumps(batch_ids), "SUCCESS", datetime.now(timezone.utc).isoformat()))
    store.conn.commit()
    # baseline_daily_v0 keeps the registry's market/sector eligibility gates;
    # these context factors are intentionally not fabricated from quote-only data.
    candidates=rank_candidates(factors,quotes,max_candidates,required_factor_ids=("M06","S01","S02","S05"))
    if calendar is None or not bool(calendar[0]):
        status="BLOCKED"; reason="NON_TRADING_DAY_OR_CALENDAR_MISSING"; candidates=[]
    elif snapshot_status and snapshot_status != "VALID":
        status="BLOCKED"; reason="SNAPSHOT_QUALITY_GATE:" + snapshot_status; candidates=[]
    elif not snapshot_gate or snapshot_gate[0] != "SUCCESS" or not quotes:
        status="BLOCKED"; reason="SNAPSHOT_SOURCE_NOT_VALID"; candidates=[]
    elif not candidates:
        status="NO_CANDIDATE"; reason="L1_HISTORY_OR_ELIGIBILITY_INSUFFICIENT"
    else:
        status="VALID"; reason=None
    now=datetime.now(timezone.utc).isoformat(); signal={"signal_id":_signal_id(trade_date,cutoff,strategy_version,registry_version),"trade_date":trade_date,"decision_cutoff":cutoff,"published_at":now,"strategy_version":strategy_version,"factor_registry_version":registry_version,"data_status":status,"data_status_reason":reason,"market_asof":row[0],"source_batch_ids":batch_ids,"created_at":now}
    store.insert_signal(signal,candidates)
    all_security_ids=[q["security_id"] for q in quotes]
    rejections=build_rejections(factors,all_security_ids,required_factor_ids=("M06","S01","S02","S05"),quotes=quotes)
    rejection_ids={r["security_id"] for r in rejections}; selected_ids={c["security_id"] for c in candidates}
    if status == "VALID":
        for sid in all_security_ids:
            if sid not in selected_ids and sid not in rejection_ids:
                rejections.append({"security_id":sid,"reason_code":"RANK_LIMIT","factor_refs":[],"details":{"candidate_limit":max_candidates}})
    elif status != "NO_CANDIDATE":
        for rejection in rejections: rejection["reason_code"] = status
    for rejection in rejections: rejection["signal_id"] = signal["signal_id"]
    store.insert_rejections(rejections)
    _pending(store,signal["signal_id"])
    return {"signal":signal,"candidates":candidates,"rejections":len(rejections),"factor_count":len(factors)}

def _pending(store, signal_id):
    now=datetime.now(timezone.utc).isoformat()
    store.insert_evaluations([{"signal_id":signal_id,"evaluation_policy_version":EVALUATION_POLICY_VERSION,"horizon_days":h,"status":"PENDING","created_at":now} for h in (1,3,5)])
