"""Safe synthetic usage demo; never touches the production database or API key."""
from __future__ import annotations
from datetime import date, datetime, timedelta, timezone
import tempfile
from .adapters.fuyao import RawBatch
from .db.store import Store
from .evaluation import advance_evaluations
from .l1 import run_l1
from .report import signal_report

def run_demo():
    path=tempfile.mktemp(prefix="ati-demo-",suffix=".db")
    store=Store("sqlite:///"+path); store.migrate("migrations")
    now=datetime(2026,11,12,6,50,tzinfo=timezone.utc); batch=RawBatch("demo-batch","demo","/synthetic",None,now,now,"SUCCESS","demo-hash", "demo://synthetic",40,now); store.insert_source_batch(batch)
    future_dates=("2026-11-13","2026-11-16","2026-11-17","2026-11-18","2026-11-19")
    store.insert_calendar_rows([{"date":d,"is_trading_day":1} for d in ("2026-11-12",)+future_dates],batch.batch_id)
    quotes=[]; members=[]
    for i in range(40):
        sid=f"{600000+i:06d}.SH"; members.append({"thscode":sid})
        quotes.append({"thscode":sid,"last_price":15+i*.01,"prev_price":14.5+i*.01,"open_price":14.8+i*.01,"high_price":15.2+i*.01,"low_price":14.8+i*.01,"volume":100000,"turnover":1500000,"name":"DEMO","is_st":False})
        history=[]
        for j in range(70):
            d=date(2026,8,1)+timedelta(days=j); close=10+j*.05+i*.001
            history.append({"thscode":sid,"date":d.isoformat(),"open":close-.05,"high":close+.2,"low":close-.2,"close":close,"prev_close":close-.05,"volume":100000,"turnover":1000000})
        store.insert_daily_rows(history,batch.batch_id)
    store.insert_security_rows([{"thscode":q["thscode"],"name":"DEMO"} for q in quotes],batch.batch_id,"demo-master",valid_from="2026-11-12T00:00:00+00:00")
    store.insert_snapshot_rows(quotes,batch.batch_id,"2026-11-12T06:50:00+00:00")
    store.insert_index_catalog([{"thscode":"IDX.DEMO","name":"演示行业"}],batch.batch_id,valid_from="2026-11-12T00:00:00+00:00")
    store.insert_index_members("IDX.DEMO",members,batch.batch_id,valid_from="2026-11-12T00:00:00+00:00")
    store.insert_limit_stats("2026-11-12",{"up_count":100,"down_count":20,"eligible_count":500},batch.batch_id,"2026-11-12T06:50:00+00:00")
    result=run_l1(store,trade_date="2026-11-12",decision_cutoff="2026-11-12T06:50:00+00:00")
    for candidate in result["candidates"]:
        for j,d in enumerate(future_dates):
            store.insert_daily_rows([{"thscode":candidate["security_id"],"date":d,"open":16,"high":17,"low":15,"close":16+j*.1}],batch.batch_id)
    evaluation=advance_evaluations(store,as_of_date="2026-11-19")
    report=signal_report(store,result["signal"]["signal_id"])
    output={"database":"temporary_demo_only","signal_status":result["signal"]["data_status"],"candidate_count":len(result["candidates"]),"candidates":[{"security_id":x["security_id"],"rank":x["rank"],"score":x["score"],"evidence":x["evidence"]} for x in result["candidates"]],"rejection_count":result["rejections"],"evaluation":evaluation,"evaluated_count":sum(x["status"]=="EVALUATED" for x in report["evaluations"]),"factor_count":result["factor_count"]}
    store.close(); return output
