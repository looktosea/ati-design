from __future__ import annotations
import json, re, sqlite3
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

class Store:
    def __init__(self, url="sqlite:///data/ati.db"):
        if not url.startswith("sqlite:///"): raise ValueError("only sqlite:/// URLs are supported in v0.1")
        self.path = Path(url[10:]); self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path); self.conn.row_factory = sqlite3.Row; self.conn.execute("PRAGMA foreign_keys=ON")
    def close(self): self.conn.close()
    def migrate(self, directory="migrations"):
        self.conn.execute("CREATE TABLE IF NOT EXISTS schema_migration (version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)")
        done = {r[0] for r in self.conn.execute("SELECT version FROM schema_migration")}
        for path in sorted(Path(directory).glob("*.sql")):
            if path.name in done: continue
            script = path.read_text(); self.conn.executescript(script)
            self.conn.execute("INSERT OR IGNORE INTO schema_migration VALUES (?,?)", (path.name, datetime.now(timezone.utc).isoformat()))
        self.conn.commit()
    def begin_job(self, job_name, idempotency_key):
        existing = self.conn.execute("select job_run_id,status from job_run where idempotency_key=?", (idempotency_key,)).fetchone()
        if existing and existing[1] in {"SUCCESS", "SKIPPED", "VALID", "NO_CANDIDATE", "BLOCKED"}: return existing[0], False
        now = datetime.now(timezone.utc).isoformat(); import hashlib; job_id = "job-" + hashlib.sha256(idempotency_key.encode()).hexdigest()
        self.conn.execute("""INSERT OR REPLACE INTO job_run(job_run_id,idempotency_key,job_name,status,started_at,finished_at,coverage_json,error_code,error_message) VALUES (?,?,?,?,?,?,?,?,?)""", (job_id,idempotency_key,job_name,"RUNNING",now,None,"{}",None,None)); self.conn.commit()
        return job_id, True

    def finish_job(self, job_id, status, coverage=None, error_code=None, error_message=None):
        self.conn.execute("update job_run set status=?,finished_at=?,coverage_json=?,error_code=?,error_message=? where job_run_id=?", (status,datetime.now(timezone.utc).isoformat(),json.dumps(coverage or {},ensure_ascii=False),error_code,error_message,job_id)); self.conn.commit()

    def insert_source_batch(self, batch, coverage=None):
        existing=self.conn.execute("select batch_id from source_batch where content_sha256=?",(batch.content_sha256,)).fetchone()
        if existing:
            return existing[0]
        self.conn.execute("""INSERT INTO source_batch(batch_id,source_name,endpoint,requested_at,source_timestamp,received_at,request_id,coverage_json,status,raw_uri,content_sha256,item_count) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""", (batch.batch_id,batch.source_name,batch.endpoint,batch.requested_at.isoformat(),batch.source_timestamp.isoformat() if batch.source_timestamp else None,batch.received_at.isoformat(),batch.request_id,json.dumps(coverage or {},ensure_ascii=False),batch.status,batch.raw_uri,batch.content_sha256,batch.item_count)); self.conn.commit(); return batch.batch_id
    def insert_security_rows(self, rows, batch_id, snapshot_version, valid_from=None):
        valid_from = valid_from or datetime.now(timezone.utc).isoformat()
        for row in rows:
            ticker = str(row.get("ticker") or row.get("code") or row.get("symbol") or row.get("thscode", "")).split(".")[0]
            exchange = row.get("exchange") or row.get("market") or _exchange(str(row.get("thscode") or ticker))
            security_id = str(row.get("security_id") or row.get("thscode") or (f"{ticker}.{exchange}" if exchange else ticker))
            name = row.get("name") or row.get("security_name")
            is_st = _is_st(name)
            self.conn.execute("INSERT OR REPLACE INTO security_master_snapshot VALUES (?,?,?,?,?,?,?,?,?,?)", (security_id,ticker,exchange,name,row.get("listed_date"),is_st,"VERIFIED_NAME_ONLY" if is_st is not None else "UNVERIFIED",valid_from,snapshot_version,batch_id))
        self.conn.commit()
    def insert_calendar_rows(self, rows, batch_id):
        for row in rows:
            if isinstance(row, str): date, is_day, session = row, 1, None
            else: date = str(row.get("trade_date") or row.get("date")); is_day = int(row.get("is_trading_day", row.get("is_open", True))); session = row.get("session")
            date = _calendar_date(date)
            self.conn.execute("INSERT OR REPLACE INTO trading_calendar VALUES (?,?,?,?)", (date,is_day,session,batch_id))
        self.conn.commit()
    def insert_snapshot_rows(self, rows, batch_id, as_of=None):
        as_of = as_of or datetime.now(timezone.utc).isoformat(); count = 0
        for row in rows:
            normalized = normalize_quote(row)
            security_id = normalized["security_id"]
            self.conn.execute("""INSERT OR REPLACE INTO quote_snapshot
                (security_id,event_time,source_batch_id,ticker,exchange,name,last_price,prev_close,open,high,low,
                 volume_shares,turnover_cny,price_change_pct,trade_status,is_st,status,source_name,raw_ref)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (security_id,as_of,batch_id,normalized["ticker"],normalized["exchange"],normalized["name"],normalized["last_price"],normalized["prev_close"],normalized["open"],normalized["high"],normalized["low"],normalized["volume_shares"],normalized["turnover_cny"],normalized["price_change_pct"],normalized["trade_status"],normalized["is_st"],"VALID","fuyao",None))
            self.conn.execute("INSERT OR REPLACE INTO intraday_bar(security_id,event_time,source_batch_id,last_price,volume_shares,turnover_cny,source_name) VALUES (?,?,?,?,?,?,?)", (security_id,as_of,batch_id,normalized["last_price"],normalized["volume_shares"],normalized["turnover_cny"],"fuyao")); count += 1
        self.conn.commit(); return count

    def insert_index_catalog(self, rows, batch_id, snapshot_version="index-v1", valid_from=None, kind="ths"):
        valid_from = valid_from or datetime.now(timezone.utc).isoformat(); count = 0
        for row in rows:
            index_id = str(row.get("index_id") or row.get("thscode") or row.get("code") or row.get("ticker") or "")
            if not index_id: continue
            self.conn.execute("""INSERT OR REPLACE INTO index_master
                (index_id,index_code,name,kind,exchange,valid_from,valid_to,snapshot_version,source_batch_id)
                VALUES (?,?,?,?,?,?,?,?,?)""", (index_id,str(row.get("index_code") or row.get("ticker") or index_id),row.get("name") or row.get("index_name"),kind,row.get("exchange"),valid_from,row.get("valid_to"),snapshot_version,batch_id)); count += 1
        self.conn.commit(); return count

    def insert_index_members(self, index_id, rows, batch_id, snapshot_version="index-v1", valid_from=None):
        valid_from = valid_from or datetime.now(timezone.utc).isoformat(); count = 0
        for row in rows:
            sid = str(row.get("security_id") or row.get("thscode") or row.get("ticker") or row.get("code") or "")
            if not sid: continue
            self.conn.execute("""INSERT OR REPLACE INTO index_membership_snapshot
                (index_id,security_id,valid_from,valid_to,snapshot_version,source_batch_id) VALUES (?,?,?,?,?,?)""", (index_id,sid,row.get("valid_from",valid_from),row.get("valid_to"),snapshot_version,batch_id)); count += 1
        self.conn.commit(); return count

    def insert_index_snapshot_rows(self, rows, batch_id, event_time=None):
        event_time = event_time or datetime.now(timezone.utc).isoformat(); count = 0
        for row in rows:
            index_id = str(row.get("index_id") or row.get("thscode") or row.get("code") or "")
            if not index_id: continue
            self.conn.execute("""INSERT OR REPLACE INTO index_quote_snapshot
                (index_id,event_time,source_batch_id,last_price,prev_close,price_change_pct,turnover_cny,status)
                VALUES (?,?,?,?,?,?,?,?)""", (index_id,event_time,batch_id,row.get("last_price",row.get("price",row.get("close"))),row.get("prev_close",row.get("prev_price")),row.get("price_change_pct",row.get("change_pct")),row.get("turnover_cny",row.get("turnover",row.get("amount"))),"VALID")); count += 1
        self.conn.commit(); return count

    def insert_shadow_observation(self, observation_id, source_name, endpoint, security_id, event_time, payload, batch_id, status="SUCCESS"):
        self.conn.execute("""INSERT OR REPLACE INTO shadow_observation
            (observation_id,source_name,endpoint,security_id,event_time,received_at,status,raw_json,source_batch_id)
            VALUES (?,?,?,?,?,?,?,?,?)""", (observation_id,source_name,endpoint,security_id,event_time,datetime.now(timezone.utc).isoformat(),status,json.dumps(payload,ensure_ascii=False),batch_id)); self.conn.commit()

    def insert_index_daily_rows(self, index_id, rows, batch_id, price_version="forward-v1"):
        count=0
        for row in rows:
            date=_calendar_date(row.get("trade_date") or row.get("date") or row.get("date_ms") or row.get("timestamp"))
            if not date: continue
            self.conn.execute("""INSERT OR REPLACE INTO index_daily_bar
                (index_id,trade_date,price_version,open,high,low,close,prev_close,turnover_cny,source_batch_id)
                VALUES (?,?,?,?,?,?,?,?,?,?)""", (index_id,date,price_version,row.get("open",row.get("open_price")),row.get("high",row.get("high_price")),row.get("low",row.get("low_price")),row.get("close",row.get("close_price")),row.get("prev_close",row.get("prev_price")),row.get("turnover_cny",row.get("turnover",row.get("amount"))),batch_id)); count+=1
        self.conn.commit(); return count

    def insert_limit_stats(self, trade_date, payload, batch_id, event_time=None):
        event_time = event_time or datetime.now(timezone.utc).isoformat(); data = payload if isinstance(payload, dict) else {}
        def pick(*keys):
            for key in keys:
                if data.get(key) is not None: return data.get(key)
            return None
        self.conn.execute("""INSERT OR REPLACE INTO limit_stat_snapshot
            (trade_date,event_time,source_batch_id,up_count,down_count,break_count,eligible_count,status,raw_json)
            VALUES (?,?,?,?,?,?,?,?,?)""", (trade_date,event_time,batch_id,pick("up_count","limit_up_count","limit_up_stock_count","rise_count"),pick("down_count","limit_down_count","limit_down_stock_count","fall_count"),pick("break_count","limit_break_count","open_stock_count"),pick("eligible_count","total_count","touched_limit_up_stock_count"),"VALID",json.dumps(data,ensure_ascii=False)))
        self.conn.commit()

    def insert_daily_rows(self, rows, batch_id, price_version="forward-v1"):
        count = 0
        for row in rows:
            sid = str(row.get("security_id") or row.get("thscode") or row.get("ticker") or "")
            date = _calendar_date(row.get("trade_date") or row.get("date") or row.get("date_ms") or row.get("timestamp"))
            if not sid or not date: continue
            self.conn.execute("""INSERT OR REPLACE INTO daily_bar
                (security_id,trade_date,price_version,open,high,low,close,prev_close,volume_shares,turnover_cny,source_batch_id)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""", (sid,date,price_version,row.get("open",row.get("open_price")),row.get("high",row.get("high_price")),row.get("low",row.get("low_price")),row.get("close",row.get("close_price")),row.get("prev_close",row.get("prev_price")),row.get("volume_shares",row.get("volume")),row.get("turnover_cny",row.get("turnover",row.get("amount"))),batch_id)); count += 1
        self.conn.commit(); return count

    def insert_factor_values(self, values):
        for value in values:
            self.conn.execute("""INSERT OR REPLACE INTO factor_value
                (factor_id,factor_version,security_id,decision_cutoff,raw_value_json,transformed_value_json,validity,missing_reason,coverage,data_asof,source_batch_ids,explanation)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""", (value["factor_id"],value["factor_version"],value.get("security_id") or "",value["decision_cutoff"],json.dumps(value.get("raw_value"),ensure_ascii=False),json.dumps(value.get("transformed_value"),ensure_ascii=False),value["validity"],value.get("missing_reason"),value.get("coverage"),value.get("data_asof"),json.dumps(value.get("source_batch_ids",[])),json.dumps(value.get("explanation"),ensure_ascii=False) if isinstance(value.get("explanation"),(dict,list)) else value.get("explanation")))
        self.conn.commit()

    def insert_signal(self, signal, candidates=()):
        self.conn.execute("delete from signal_candidate_evaluation where signal_id=?", (signal["signal_id"],))
        self.conn.execute("delete from signal_evaluation where signal_id=?", (signal["signal_id"],))
        self.conn.execute("delete from signal_rejection where signal_id=?", (signal["signal_id"],))
        self.conn.execute("delete from signal_candidate where signal_id=?", (signal["signal_id"],))
        self.conn.execute("""INSERT OR IGNORE INTO signal_snapshot
            (signal_id,trade_date,decision_cutoff,published_at,strategy_version,factor_registry_version,data_status,data_status_reason,market_asof,source_batch_ids,created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""", (signal["signal_id"],signal["trade_date"],signal["decision_cutoff"],signal["published_at"],signal["strategy_version"],signal["factor_registry_version"],signal["data_status"],signal.get("data_status_reason"),signal.get("market_asof"),json.dumps(signal.get("source_batch_ids",[])),signal.get("created_at",datetime.now(timezone.utc).isoformat())))
        for candidate in candidates:
            self.conn.execute("""INSERT OR IGNORE INTO signal_candidate
                (signal_id,security_id,rank,score,eligibility_status,strategy_ids,evidence_json,risks_json,factor_refs)
                VALUES (?,?,?,?,?,?,?,?,?)""", (signal["signal_id"],candidate["security_id"],candidate["rank"],candidate.get("score"),candidate["eligibility_status"],json.dumps(candidate.get("strategy_ids",[])),json.dumps(candidate.get("evidence",[]),ensure_ascii=False),json.dumps(candidate.get("risks",[]),ensure_ascii=False),json.dumps(candidate.get("factor_refs",[]))))
        self.conn.commit()

    def insert_candidate_evaluations(self, evaluations):
        for e in evaluations:
            self.conn.execute("""INSERT OR REPLACE INTO signal_candidate_evaluation
                (signal_id,security_id,evaluation_policy_version,horizon_days,reference_price,reference_time,status,gross_return,net_reference_return,max_adverse_move,endpoint_trade_date,unresolved_reason,created_at,evaluated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (e["signal_id"],e["security_id"],e["evaluation_policy_version"],e["horizon_days"],e.get("reference_price"),e.get("reference_time"),e["status"],e.get("gross_return"),e.get("net_reference_return"),e.get("max_adverse_move"),e.get("endpoint_trade_date"),e.get("unresolved_reason"),e.get("created_at",datetime.now(timezone.utc).isoformat()),e.get("evaluated_at")))
        self.conn.commit()

    def ensure_candidate_evaluations(self, evaluations):
        for e in evaluations:
            self.conn.execute("""INSERT OR IGNORE INTO signal_candidate_evaluation
                (signal_id,security_id,evaluation_policy_version,horizon_days,reference_price,reference_time,status,gross_return,net_reference_return,max_adverse_move,endpoint_trade_date,unresolved_reason,created_at,evaluated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (e["signal_id"],e["security_id"],e["evaluation_policy_version"],e["horizon_days"],e.get("reference_price"),e.get("reference_time"),e["status"],e.get("gross_return"),e.get("net_reference_return"),e.get("max_adverse_move"),e.get("endpoint_trade_date"),e.get("unresolved_reason"),e.get("created_at",datetime.now(timezone.utc).isoformat()),e.get("evaluated_at")))
        self.conn.commit()

    def insert_rejections(self, rejections):
        for r in rejections:
            self.conn.execute("""INSERT OR REPLACE INTO signal_rejection
                (signal_id,security_id,reason_code,factor_refs,details_json,created_at) VALUES (?,?,?,?,?,?)""", (r["signal_id"],r["security_id"],r["reason_code"],json.dumps(r.get("factor_refs",[])),json.dumps(r.get("details",{}),ensure_ascii=False),r.get("created_at",datetime.now(timezone.utc).isoformat())))
        self.conn.commit()

    def insert_evaluations(self, evaluations):
        for e in evaluations:
            self.conn.execute("""INSERT OR REPLACE INTO signal_evaluation
                (signal_id,evaluation_policy_version,horizon_days,reference_price,reference_time,status,gross_return,net_reference_return,max_adverse_move,endpoint_trade_date,unresolved_reason,created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""", (e["signal_id"],e["evaluation_policy_version"],e["horizon_days"],e.get("reference_price"),e.get("reference_time"),e["status"],e.get("gross_return"),e.get("net_reference_return"),e.get("max_adverse_move"),e.get("endpoint_trade_date"),e.get("unresolved_reason"),e.get("created_at",datetime.now(timezone.utc).isoformat())))
        self.conn.commit()

def _calendar_date(value):
    if value is None: return None
    if isinstance(value,(int,float)) or (isinstance(value,str) and value.isdigit() and len(value)>=11):
        try: return datetime.fromtimestamp(float(value)/(1000 if float(value)>10_000_000_000 else 1),timezone.utc).astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()
        except (TypeError,ValueError,OverflowError): return None
    value = str(value)
    if len(value) == 8 and value.isdigit(): return f"{value[:4]}-{value[4:6]}-{value[6:]}"
    return value[:10] if "T" in value else value

def normalize_quote(row):
    ticker = str(row.get("ticker") or row.get("code") or row.get("symbol") or row.get("thscode") or "")
    exchange = row.get("exchange") or row.get("market") or _exchange(ticker)
    security_id = str(row.get("security_id") or row.get("thscode") or (f"{ticker}.{exchange}" if exchange else ticker))
    return {"security_id": security_id, "ticker": ticker.split(".")[0], "exchange": exchange,
            "name": row.get("name") or row.get("security_name"),
            "last_price": row.get("last_price", row.get("price", row.get("close"))),
            "prev_close": row.get("prev_close", row.get("prev_price")),
            "open": row.get("open", row.get("open_price")), "high": row.get("high", row.get("high_price")),
            "low": row.get("low", row.get("low_price")), "volume_shares": row.get("volume_shares", row.get("volume")),
            "turnover_cny": row.get("turnover_cny", row.get("turnover", row.get("amount"))),
            "price_change_pct": row.get("price_change_pct", row.get("price_change_ratio_pct", row.get("change_pct"))),
            "trade_status": row.get("trade_status"), "is_st": row.get("is_st")}

def _exchange(ticker):
    if ticker.endswith((".SH",".SZ",".BJ")): return ticker.rsplit(".",1)[1]
    if re.fullmatch(r"6\d{5}", ticker): return "SH"
    if re.fullmatch(r"[03]\d{5}", ticker): return "SZ"
    if re.fullmatch(r"[48]\d{5}", ticker): return "BJ"
    return None
def _is_st(name):
    if name is None: return None
    return bool(re.match(r"\s*\*?ST", str(name), re.I))
