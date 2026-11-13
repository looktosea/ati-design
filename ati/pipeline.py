from __future__ import annotations
import json
from datetime import datetime, timezone
from .adapters.fuyao import FuyaoClient, _items
from .db.store import Store
from .quality.gate import evaluate_snapshot

def run_foundation(settings, store: Store):
    client = FuyaoClient(settings); store.migrate()
    universe_pages = client.current_a_shares_all()
    universe = []
    valid_from = datetime.now(timezone.utc).isoformat()
    page_batch_ids = []
    for envelope, batch in universe_pages:
        canonical_batch_id = store.insert_source_batch(batch, {"page_size": len(_items(envelope.data)), "universe_page": len(page_batch_ids)})
        page_rows = _items(envelope.data); universe.extend(page_rows); page_batch_ids.append(batch.batch_id)
        store.insert_security_rows(page_rows, canonical_batch_id, "universe-v1", valid_from=valid_from)
    envelope, batch = client.request_and_save("/api/a-share/calendar/trading-days", {}); canonical_calendar_batch_id = store.insert_source_batch(batch)
    calendar = _items(envelope.data); store.insert_calendar_rows(calendar, canonical_calendar_batch_id)
    snapshot_pages = client.market_snapshot_all(); quotes=[]; snapshot_batch_ids=[]; page_gates=[]; page_received=[]; page_timestamps=[]
    for snapshot_envelope, snapshot_batch in snapshot_pages:
        canonical_id=store.insert_source_batch(snapshot_batch,{"page_size":len(_items(snapshot_envelope.data)),"snapshot_page":len(snapshot_batch_ids)})
        page_rows=_items(snapshot_envelope.data); quotes.extend(page_rows); snapshot_batch_ids.append(canonical_id); page_received.append(snapshot_batch.received_at); page_timestamps.append(snapshot_batch.source_timestamp)
        page_gates.append(evaluate_snapshot(page_rows,source_timestamp=snapshot_batch.source_timestamp,received_at=snapshot_batch.received_at,expected_min=1))
    snapshot_asof=max((x for x in page_timestamps if x),default=max(page_received).isoformat() if page_received else None)
    gate_reasons=sorted({reason for g in page_gates for reason in g.reasons}); gate_status="BLOCKED" if gate_reasons or not quotes else "VALID"; gate_coverage=sum(len(_items(e.data)) for e,b in snapshot_pages)/max(1,len(quotes))
    stored=sum(store.insert_snapshot_rows(_items(snapshot_envelope.data),canonical_id,snapshot_asof.isoformat() if hasattr(snapshot_asof,"isoformat") else snapshot_asof) for (snapshot_envelope,snapshot_batch),canonical_id in zip(snapshot_pages,snapshot_batch_ids))
    quote_ids = {str(row.get("ticker") or row.get("thscode") or row.get("code") or "").split(".")[0] for row in quotes}
    universe_ids = {str(row.get("ticker") or row.get("thscode") or row.get("code") or "").split(".")[0] for row in universe}
    missing_from_universe = sorted(x for x in quote_ids if x and x not in universe_ids)
    return {"universe":len(universe),"universe_pages":len(universe_pages),"snapshot":stored,"snapshot_pages":len(snapshot_pages),"data_status":gate_status,"quality_reasons":gate_reasons,"coverage":gate_coverage,"batch_ids":snapshot_batch_ids,"snapshot_ids_missing_from_universe":len(missing_from_universe)}

def import_daily_history(settings, store, codes, start=None, end=None):
    """Fetch and append Fuyao daily history in documented batches of <=10 codes."""
    from .adapters.fuyao import FuyaoClient, _items
    codes = [str(code).strip() for code in codes if str(code).strip()]
    key = "daily-history-v3:" + ",".join(sorted(codes)) + f":{start or ''}:{end or ''}"
    job_id, should_run = store.begin_job("daily_history", key)
    if not should_run: return {"status":"SKIPPED", "job_run_id":job_id, "requested_codes":len(codes)}
    try:
        client = FuyaoClient(settings); store.migrate(); total = 0; batches = 0; failed = []
        for offset in range(0, len(codes), 10):
            group = codes[offset:offset + 10]
            try:
                envelope, batch = client.daily_history_batch(group, start, end)
                data = envelope.data if isinstance(envelope.data, dict) else {}
                rows = _items(data)
                parent_code = data.get("thscode")
                rows = [{**row, "thscode": row.get("thscode", parent_code)} for row in rows if isinstance(row, dict)]
                canonical_batch_id = store.insert_source_batch(batch, {"requested_codes": group, "stored_rows": len(rows)})
                flat = []
                for row in rows:
                    child_rows = row.get("item") if isinstance(row, dict) else None
                    if not isinstance(child_rows, list): child_rows = row.get("items") if isinstance(row, dict) else None
                    if isinstance(child_rows, list):
                        parent = row.get("thscode") or row.get("security_id")
                        for child in child_rows: flat.append({**child, "thscode": child.get("thscode", parent)})
                    elif isinstance(row, dict): flat.append(row)
                total += store.insert_daily_rows(flat, canonical_batch_id); batches += 1
            except Exception as exc:
                failed.append({"codes":group,"error_code":type(exc).__name__})
        result={"status":"SUCCESS" if not failed else ("PARTIAL" if total else "FAILED"),"job_run_id":job_id,"requested_codes":len(codes),"stored_daily_rows":total,"batches":batches,"failed_batches":failed}
        store.finish_job(job_id,result["status"],result)
        return result
    except Exception as exc:
        store.finish_job(job_id,"FAILED",{},type(exc).__name__,"daily history import failed")
        raise

def import_index_catalog(settings, store, kind="ths"):
    from .adapters.fuyao import FuyaoClient, _items
    key="index-catalog:"+kind; job_id, should_run=store.begin_job("index_catalog",key)
    if not should_run: return {"status":"SKIPPED","job_run_id":job_id}
    try:
        client=FuyaoClient(settings); store.migrate(); envelope,batch=client.index_catalog(kind); rows=_items(envelope.data)
        canonical_batch_id=store.insert_source_batch(batch,{"kind":kind,"rows":len(rows)}); count=store.insert_index_catalog(rows,canonical_batch_id,kind=kind)
        result={"status":"SUCCESS","job_run_id":job_id,"kind":kind,"indexes":count}; store.finish_job(job_id,"SUCCESS",result); return result
    except Exception as exc:
        store.finish_job(job_id,"FAILED",{},type(exc).__name__,"index catalog import failed"); raise

def import_index_members(settings, store, index_ids):
    from .adapters.fuyao import FuyaoClient, _items
    ids=sorted({str(x).strip() for x in index_ids if str(x).strip()}); key="index-members:"+",".join(ids); job_id, should_run=store.begin_job("index_members",key)
    if not should_run: return {"status":"SKIPPED","job_run_id":job_id,"indexes":len(ids)}
    try:
        client=FuyaoClient(settings); store.migrate(); total=0; failures=[]
        for index_id in ids:
            try:
                envelope,batch=client.index_members(index_id); rows=_items(envelope.data); canonical_batch_id=store.insert_source_batch(batch,{"index_id":index_id,"rows":len(rows)}); total+=store.insert_index_members(index_id,rows,canonical_batch_id)
            except Exception as exc: failures.append({"index_id":index_id,"error_code":type(exc).__name__})
        status="SUCCESS" if not failures else ("PARTIAL" if total else "FAILED"); result={"status":status,"job_run_id":job_id,"indexes":len(ids),"members":total,"failed":failures}; store.finish_job(job_id,status,result); return result
    except Exception as exc:
        store.finish_job(job_id,"FAILED",{},type(exc).__name__,"index member import failed"); raise

def import_index_snapshots(settings, store, index_ids):
    from .adapters.fuyao import FuyaoClient, _items
    ids=sorted({str(x).strip() for x in index_ids if str(x).strip()}); key="index-snapshot:"+",".join(ids); job_id, should_run=store.begin_job("index_snapshot",key)
    if not should_run: return {"status":"SKIPPED","job_run_id":job_id}
    try:
        client=FuyaoClient(settings); store.migrate(); envelope,batch=client.index_snapshot(ids); rows=_items(envelope.data); canonical_batch_id=store.insert_source_batch(batch,{"index_ids":ids,"rows":len(rows)}); count=store.insert_index_snapshot_rows(rows,canonical_batch_id,batch.source_timestamp.isoformat() if batch.source_timestamp else None)
        result={"status":"SUCCESS","job_run_id":job_id,"indexes":count}; store.finish_job(job_id,"SUCCESS",result); return result
    except Exception as exc:
        store.finish_job(job_id,"FAILED",{},type(exc).__name__,"index snapshot import failed"); raise

def import_limit_statistics(settings, store, trade_date=None):
    from .adapters.fuyao import FuyaoClient, _items
    key="limit-statistics-v2:"+(trade_date or "latest"); job_id, should_run=store.begin_job("limit_statistics",key)
    if not should_run: return {"status":"SKIPPED","job_run_id":job_id}
    try:
        client=FuyaoClient(settings); store.migrate(); envelope,batch=client.limit_statistics(trade_date); data=envelope.data if isinstance(envelope.data,dict) else {}; rows=_items(envelope.data); canonical_batch_id=store.insert_source_batch(batch,{"trade_date":trade_date,"rows":len(rows)}); store.insert_limit_stats(trade_date or datetime.now(timezone.utc).date().isoformat(),data,canonical_batch_id,batch.source_timestamp.isoformat() if batch.source_timestamp else None)
        result={"status":"SUCCESS","job_run_id":job_id,"trade_date":trade_date}; store.finish_job(job_id,"SUCCESS",result); return result
    except Exception as exc:
        store.finish_job(job_id,"FAILED",{},type(exc).__name__,"limit statistics import failed"); raise

def import_index_history(settings, store, index_ids, start=None, end=None):
    from .adapters.fuyao import FuyaoClient, _items
    ids=sorted({str(x).strip() for x in index_ids if str(x).strip()}); key="index-history:"+",".join(ids)+f":{start or ''}:{end or ''}"; job_id,should_run=store.begin_job("index_history",key)
    if not should_run: return {"status":"SKIPPED","job_run_id":job_id}
    try:
        client=FuyaoClient(settings); store.migrate(); total=0; failures=[]
        for index_id in ids:
            try:
                envelope,batch=client.index_daily_history(index_id,start,end); rows=_items(envelope.data); canonical_batch_id=store.insert_source_batch(batch,{"index_id":index_id,"rows":len(rows)}); total+=store.insert_index_daily_rows(index_id,rows,canonical_batch_id)
            except Exception as exc: failures.append({"index_id":index_id,"error_code":type(exc).__name__})
        status="SUCCESS" if not failures else ("PARTIAL" if total else "FAILED"); result={"status":status,"job_run_id":job_id,"indexes":len(ids),"daily_rows":total,"failed":failures}; store.finish_job(job_id,status,result); return result
    except Exception as exc:
        store.finish_job(job_id,"FAILED",{},type(exc).__name__,"index history import failed"); raise

def collect_shadow(settings, store, secids):
    from .adapters.eastmoney import EastmoneyClient
    if not settings.eastmoney_shadow_enabled: return {"status":"BLOCKED","reason":"EASTMONEY_SHADOW_ENABLED_FALSE"}
    client=EastmoneyClient(settings); observations=0; failures=[]
    for secid in secids:
        for kind,fn in (("trends",client.trends),("capital_flow",client.capital_flow)):
            try:
                payload,batch=fn(secid); canonical_batch_id=store.insert_source_batch(batch,{"mode":"SHADOW","security_id":secid,"kind":kind}); oid=f"{batch.batch_id}:{secid}:{kind}"; store.insert_shadow_observation(oid,"eastmoney_shadow",batch.endpoint,secid,batch.source_timestamp.isoformat() if batch.source_timestamp else None,payload,canonical_batch_id); observations+=1
            except Exception as exc: failures.append({"security_id":secid,"kind":kind,"error_code":type(exc).__name__})
    return {"status":"SUCCESS" if not failures else ("PARTIAL" if observations else "FAILED"),"observations":observations,"failed":failures}
