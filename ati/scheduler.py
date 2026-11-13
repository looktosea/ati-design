"""Five-cutoff scheduler with calendar and business-key idempotency."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from .adapters.fuyao import FuyaoClient, _items
from .db.store import Store
from .l1 import run_l1
from .quality.gate import evaluate_snapshot

def due_cutoffs(settings, now=None):
    now = now or datetime.now(timezone.utc)
    local = now.astimezone(settings.timezone)
    return [datetime.combine(local.date(), t, settings.timezone) for t in settings.signal_times if t <= local.timetz().replace(tzinfo=None)]

def _calendar_is_open(store, trade_date):
    row=store.conn.execute("select is_trading_day from trading_calendar where trade_date=?",(trade_date,)).fetchone()
    return bool(row and row[0])

def run_due(settings, store, now=None):
    """Run all configured cutoffs that have passed, skipping existing signals."""
    now=now or datetime.now(timezone.utc); local=now.astimezone(settings.timezone); results=[]
    for cutoff_local in due_cutoffs(settings,now):
        trade_date=cutoff_local.date().isoformat(); cutoff=cutoff_local.astimezone(timezone.utc).isoformat(); key=f"signal:{trade_date}:{cutoff}:{settings.max_candidates}"
        job_id,should_run=store.begin_job("scheduled_signal",key)
        if not should_run: results.append({"status":"SKIPPED","job_run_id":job_id,"trade_date":trade_date,"cutoff":cutoff}); continue
        if not _calendar_is_open(store,trade_date):
            result={"status":"BLOCKED","job_run_id":job_id,"trade_date":trade_date,"cutoff":cutoff,"reason":"NON_TRADING_DAY_OR_CALENDAR_MISSING"}; store.finish_job(job_id,"BLOCKED",result); results.append(result); continue
        try:
            client=FuyaoClient(settings); pages=client.market_snapshot_all(); rows=[]; batch_ids=[]; gates=[]; timestamps=[]; received=[]
            for envelope,batch in pages:
                page_rows=_items(envelope.data); rows.extend(page_rows); canonical_id=store.insert_source_batch(batch,{"rows":len(page_rows),"cutoff":cutoff,"snapshot_page":len(batch_ids)}); batch_ids.append(canonical_id); received.append(batch.received_at); timestamps.append(batch.source_timestamp); gates.append(evaluate_snapshot(page_rows,source_timestamp=batch.source_timestamp,received_at=batch.received_at,expected_min=1))
            asof=max((x for x in timestamps if x),default=max(received).isoformat() if received else None); quality="BLOCKED" if any(g.status != "VALID" for g in gates) else "VALID"
            for (envelope,batch),canonical_id in zip(pages,batch_ids): store.insert_snapshot_rows(_items(envelope.data),canonical_id,asof.isoformat() if hasattr(asof,"isoformat") else asof)
            signal=run_l1(store,trade_date=trade_date,decision_cutoff=cutoff,max_candidates=settings.max_candidates,snapshot_status=quality)
            status=signal["signal"]["data_status"]; store.finish_job(job_id,status,{"quality":quality,"rows":len(rows),"pages":len(pages),"signal_id":signal["signal"]["signal_id"]}); results.append({"status":status,"job_run_id":job_id,"signal_id":signal["signal"]["signal_id"],"candidates":len(signal["candidates"])})
        except Exception as exc:
            store.finish_job(job_id,"FAILED",{},type(exc).__name__,"scheduled signal failed"); results.append({"status":"FAILED","job_run_id":job_id,"error_code":type(exc).__name__})
    return results
