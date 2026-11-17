"""Auditable signal and data coverage reports."""
from __future__ import annotations
import json

def signal_report(store, signal_id=None, *, rejection_limit=None, include_factor_sample=True):
    if signal_id:
        signal=store.conn.execute("select * from signal_snapshot where signal_id=?",(signal_id,)).fetchone()
    else:
        signal=store.conn.execute("select * from signal_snapshot order by created_at desc limit 1").fetchone()
    if not signal: return {"status":"MISSING","reason":"SIGNAL_NOT_FOUND"}
    signal=dict(signal); candidates=[dict(r) for r in store.conn.execute("select * from signal_candidate where signal_id=? order by rank",(signal["signal_id"],))]
    for c in candidates:
        for key in ("strategy_ids","evidence_json","risks_json","factor_refs"): 
            try: c[key.removesuffix("_json") if key.endswith("_json") else key]=json.loads(c.pop(key))
            except (TypeError,ValueError,KeyError): pass
    evaluations=[dict(r) for r in store.conn.execute("select * from signal_candidate_evaluation where signal_id=? order by security_id,horizon_days",(signal["signal_id"],))]
    rejection_total=store.conn.execute("select count(*) from signal_rejection where signal_id=?",(signal["signal_id"],)).fetchone()[0]
    rejection_sql="select * from signal_rejection where signal_id=? order by security_id"
    rejection_params=[signal["signal_id"]]
    if rejection_limit is not None:
        rejection_sql += " limit ?"
        rejection_params.append(max(0, int(rejection_limit)))
    rejections=[dict(r) for r in store.conn.execute(rejection_sql,tuple(rejection_params))]
    for r in rejections:
        try: r["factor_refs"]=json.loads(r["factor_refs"]); r["details"]=json.loads(r["details_json"]); del r["details_json"]
        except (TypeError,ValueError): pass
    factors=[]
    if include_factor_sample:
        factors=[dict(r) for r in store.conn.execute("select factor_id,security_id,validity,missing_reason,coverage,data_asof,source_batch_ids from factor_value where decision_cutoff=? order by factor_id,security_id limit 1000",(signal["decision_cutoff"],))]
    for f in factors:
        try: f["source_batch_ids"]=json.loads(f["source_batch_ids"])
        except (TypeError,ValueError): pass
    return {"signal":signal,"candidates":candidates,"rejections":rejections,"evaluations":evaluations,"factor_sample":factors,"candidate_count":len(candidates),"rejection_count":len(rejections),"rejection_total":rejection_total,"rejections_truncated":rejection_limit is not None and rejection_total > len(rejections)}
