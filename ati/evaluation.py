"""Forward signal evaluation using the stored daily calendar and prices."""
from __future__ import annotations
import json
from datetime import date, datetime, timezone
from .l1 import EVALUATION_POLICY_VERSION

def _trade_dates(store, start, horizons=(1,3,5)):
    rows=[r[0] for r in store.conn.execute("select trade_date from trading_calendar where is_trading_day=1 and trade_date>? order by trade_date",(start,))]
    return {h:(rows[h-1] if len(rows)>=h else None) for h in horizons}

def _as_date(value): return str(value)[:10]

def initialize_candidate_evaluations(store, signal_id, policy_version=EVALUATION_POLICY_VERSION):
    rows=store.conn.execute("select security_id from signal_candidate where signal_id=?",(signal_id,)).fetchall(); now=datetime.now(timezone.utc).isoformat()
    store.ensure_candidate_evaluations([{"signal_id":signal_id,"security_id":r[0],"evaluation_policy_version":policy_version,"horizon_days":h,"status":"PENDING","created_at":now} for r in rows for h in (1,3,5)])
    return len(rows)*3

def advance_evaluations(store, *, as_of_date=None, cost_bps=30, policy_version=EVALUATION_POLICY_VERSION):
    """Advance mature candidate evaluations without deleting constrained samples."""
    as_of_date=as_of_date or datetime.now(timezone.utc).date().isoformat(); now=datetime.now(timezone.utc).isoformat(); updated=0
    signals=store.conn.execute("select signal_id,trade_date,market_asof from signal_snapshot where data_status in ('VALID','NO_CANDIDATE')").fetchall()
    for signal_id,trade_date,market_asof in signals:
        initialize_candidate_evaluations(store,signal_id,policy_version)
        endpoints=_trade_dates(store,trade_date)
        candidates=store.conn.execute("select security_id from signal_candidate where signal_id=?",(signal_id,)).fetchall()
        for (sid,) in candidates:
            q=store.conn.execute("select last_price,event_time from quote_snapshot where security_id=? and event_time=?",(sid,market_asof)).fetchone()
            ref=q[0] if q else None; ref_time=q[1] if q else None
            for h,endpoint in endpoints.items():
                if not endpoint: continue
                if endpoint > as_of_date: continue
                close=store.conn.execute("select close from daily_bar where security_id=? and trade_date=? order by price_version desc limit 1",(sid,endpoint)).fetchone()
                if ref is None or ref<=0:
                    status="ENTRY_UNCERTAIN"; reason="REFERENCE_QUOTE_MISSING"; gross=net=adverse=None
                elif close is None or close[0] is None:
                    status="DATA_UNRESOLVED"; reason="ENDPOINT_CLOSE_MISSING"; gross=net=adverse=None
                else:
                    gross=close[0]/ref-1; net=gross-cost_bps/10000
                    lows=[r[0] for r in store.conn.execute("select low from daily_bar where security_id=? and trade_date>? and trade_date<=? and low is not null",(sid,trade_date,endpoint))]
                    adverse=min((x/ref-1 for x in lows),default=None)
                    status="EVALUATED"; reason=None
                store.insert_candidate_evaluations([{"signal_id":signal_id,"security_id":sid,"evaluation_policy_version":policy_version,"horizon_days":h,"reference_price":ref,"reference_time":ref_time,"status":status,"gross_return":gross,"net_reference_return":net,"max_adverse_move":adverse,"endpoint_trade_date":endpoint,"unresolved_reason":reason,"created_at":now,"evaluated_at":now}]); updated+=1
    return {"as_of_date":as_of_date,"updated":updated,"cost_bps":cost_bps}
