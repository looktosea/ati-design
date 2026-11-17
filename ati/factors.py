"""First L1 factor calculations.

Functions operate on normalized rows and return the versioned factor contract. They
never turn missing inputs into zero. Minute-only and unavailable-source factors are
intentionally absent from this module.
"""
from __future__ import annotations
import math
from datetime import datetime, timezone
from statistics import mean, median, pstdev

VALIDITIES = {"VALID", "INSUFFICIENT_HISTORY", "MISSING", "STALE", "NOT_APPLICABLE", "CONFLICTED", "SOURCE_CHANGED"}

def _num(v):
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError): return None

def _factor(fid, security_id, cutoff, raw=None, transformed=None, validity="MISSING", reason=None, coverage=None, data_asof=None, batches=(), explanation=None, version="0.1.0"):
    if validity not in VALIDITIES: raise ValueError(f"invalid factor validity: {validity}")
    return {"factor_id":fid,"factor_version":version,"security_id":security_id,"decision_cutoff":cutoff,
            "raw_value":raw,"transformed_value":transformed,"validity":validity,"missing_reason":reason,
            "coverage":coverage,"data_asof":data_asof,"source_batch_ids":list(batches),"explanation":explanation}

def _asof(rows):
    vals=[r.get("event_time") or r.get("as_of") for r in rows if r.get("event_time") or r.get("as_of")]
    return max(vals) if vals else None

def _date_asof(value):
    value = str(value) if value is not None else None
    if value and len(value) == 10: return value + "T15:00:00+08:00"
    return value

def compute_snapshot_factors(quotes, cutoff, source_batch_ids=(), factor_version="0.1.0", max_age_seconds=300, data_asof=None):
    """Compute market and quote-only L1 factors for a single decision cutoff."""
    data_asof = data_asof or _asof(quotes)
    total=len(quotes); usable=[]
    for q in quotes:
        p=_num(q.get("last_price")); prev=_num(q.get("prev_close",q.get("prev_price")))
        if p is not None and prev is not None and p >= 0 and prev > 0 and q.get("security_id"):
            usable.append((q,p,prev))
    coverage=len(usable)/total if total else 0.0
    up=sum(p>prev for _,p,prev in usable)
    m01 = _factor("M01",None,cutoff,{"up_count":up,"valid_count":len(usable),"total_count":total},up/len(usable) if usable else None,"VALID" if usable else "MISSING",None,coverage,data_asof,source_batch_ids,"上涨宽度；平盘计入有效分母")
    # M03 needs per-security MA20 values and is supplied by compute_daily_factors.
    m03 = _factor("M03",None,cutoff,None,None,"MISSING","DAILY_HISTORY_REQUIRED",0.0,data_asof,source_batch_ids,"需要截至 D-1 的至少 20 个有效日线")
    r06 = _factor("R06",None,cutoff,{"total_quotes":total,"valid_quotes":len(usable)},None,"VALID" if coverage == 1.0 and total else "MISSING",None,coverage,data_asof,source_batch_ids,"报价覆盖和依赖完整性")
    # I06/I07 quote values are kept per security only when ATR is supplied later.
    return [m01,m03,r06]

def _history(history):
    rows=[]
    for r in history:
        close=_num(r.get("close",r.get("close_price"))); high=_num(r.get("high",r.get("high_price"))); low=_num(r.get("low",r.get("low_price")))
        op=_num(r.get("open",r.get("open_price"))); prev=_num(r.get("prev_close",r.get("prev_price")))
        if close is None or high is None or low is None: continue
        d=str(r.get("trade_date") or r.get("date") or "")
        if len(d) == 8 and d.isdigit(): d=f"{d[:4]}-{d[4:6]}-{d[6:]}"
        rows.append({"date":d,"close":close,"high":high,"low":low,"open":op,"prev":prev})
    rows.sort(key=lambda x:x["date"])
    return rows

def _atr(rows, n=14):
    if len(rows)<n: return None
    trs=[]
    for i,r in enumerate(rows):
        prev=rows[i-1]["close"] if i else r.get("prev")
        if prev is None: continue
        trs.append(max(r["high"]-r["low"],abs(r["high"]-prev),abs(r["low"]-prev)))
    return mean(trs[-n:]) if len(trs)>=n else None

def compute_daily_factors(security_id, history, quote, cutoff, source_batch_ids=(), factor_version="0.1.0"):
    """Compute I02/I03/I04/I06/I07/R01/R04 from completed daily bars and one quote."""
    cutoff_date = str(cutoff).replace("Z", "+00:00")[:10]
    history = [r for r in history if str(r.get("trade_date") or r.get("date") or "")[:10] < cutoff_date]
    rows=_history(history); asof=_date_asof(rows[-1]["date"]) if rows else None; out=[]; p=_num(quote.get("last_price")); prev=_num(quote.get("prev_close",quote.get("prev_price")))
    atr=_atr(rows,14)
    if len(rows)<60 or atr is None or atr <= 0:
        out.append(_factor("I02",security_id,cutoff,None,None,"INSUFFICIENT_HISTORY","NEED_60_DAYS_AND_ATR14",len(rows)/60 if rows else 0.0,asof,source_batch_ids))
    else:
        ma20=mean(r["close"] for r in rows[-20:]); ma60=mean(r["close"] for r in rows[-60:]); ma20_prev=mean(r["close"] for r in rows[-26:-6]) if len(rows)>=26 else None
        slope=(ma20-ma20_prev)/atr if ma20_prev is not None else None
        raw={"ma20_minus_ma60_atr":(ma20-ma60)/atr,"ma20_slope_20d_atr":slope,"price_minus_ma20_atr":(p-ma20)/atr if p is not None else None,"ma20":ma20,"ma60":ma60,"atr14":atr}
        trend_score = raw["ma20_minus_ma60_atr"] + (slope or 0.0) + (raw["price_minus_ma20_atr"] or 0.0)
        out.append(_factor("I02",security_id,cutoff,raw,trend_score,"VALID" if slope is not None and p is not None else "MISSING",None,1.0,asof,source_batch_ids, explanation={"trend_score": trend_score}))
    if len(rows)<60 or atr is None or atr<=0:
        for fid in ("I03","I04","R01","R04"):
            out.append(_factor(fid,security_id,cutoff,None,None,"INSUFFICIENT_HISTORY","NEED_HISTORY_AND_ATR14",len(rows)/60 if rows else 0.0,asof,source_batch_ids))
    else:
        ma20=mean(r["close"] for r in rows[-20:]); ma60=mean(r["close"] for r in rows[-60:]) if len(rows)>=60 else None
        hbase=max(r["high"] for r in rows[-10:-3]); lpull=min(r["low"] for r in rows[-3:]); depth=(hbase-lpull)/atr
        turnover=_num(quote.get("turnover_cny",quote.get("turnover"))); volume=_num(quote.get("volume_shares",quote.get("volume"))); vwap=turnover/volume if turnover is not None and volume and volume>0 else None
        day_low=_num(quote.get("low",quote.get("low_price"))); low_holds=day_low is not None and day_low >= ma20-0.5*atr
        recovered=bool(p is not None and prev is not None and p>prev and p>ma20 and vwap is not None and p>vwap and ma60 is not None and ma20>ma60 and low_holds)
        out.append(_factor("I03",security_id,cutoff,{"h_base":hbase,"l_pull":lpull,"pullback_depth_atr":depth,"recovered":recovered,"ma20":ma20,"vwap_proxy":vwap,"low_holds_ma20_minus_0_5_atr":low_holds},depth,"VALID" if p is not None else "MISSING",None,1.0,asof,source_batch_ids))
        h20=max(r["high"] for r in rows[-20:]); l20=min(r["low"] for r in rows[-20:]); width=(h20-l20)/atr
        out.append(_factor("I04",security_id,cutoff,{"h20":h20,"l20":l20,"range_width_atr":width,"breakout_distance_atr":(p-h20)/atr if p is not None else None},(p-h20)/atr if p is not None else None,"VALID" if p is not None else "MISSING",None,1.0,asof,source_batch_ids))
        overheat=(p-ma20)/atr if p is not None else None
        out.append(_factor("R01",security_id,cutoff,{"distance_to_ma20_atr":overheat,"breakout_distance_atr":(p-h20)/atr if p is not None else None},overheat,"VALID" if overheat is not None else "MISSING",None,1.0,asof,source_batch_ids))
        gaps=[]
        for i,r in enumerate(rows[-20:]):
            ref=r.get("prev") or (rows[-21+i]["close"] if len(rows)>=21 else None)
            if ref and r.get("open") is not None: gaps.append((r["open"]-ref)/ref)
        out.append(_factor("R04",security_id,cutoff,{"gap_count":len(gaps),"mean_gap":mean(gaps) if gaps else None,"max_abs_gap":max((abs(x) for x in gaps),default=None)},mean(gaps) if gaps else None,"VALID" if gaps else "MISSING",None,len(gaps)/20,asof,source_batch_ids))
    # Quote-only I06/I07 have explicit dependency on ATR; no fabricated persistence field.
    if atr is None or atr<=0 or p is None:
        out += [_factor("I06",security_id,cutoff,None,None,"INSUFFICIENT_HISTORY","ATR14_REQUIRED",0.0,asof,source_batch_ids),_factor("I07",security_id,cutoff,None,None,"INSUFFICIENT_HISTORY","ATR14_REQUIRED",0.0,asof,source_batch_ids)]
    else:
        turnover=_num(quote.get("turnover_cny",quote.get("turnover"))); volume=_num(quote.get("volume_shares",quote.get("volume"))); high=_num(quote.get("high",quote.get("high_price"))); low=_num(quote.get("low",quote.get("low_price"))); vwap=turnover/volume if turnover is not None and volume and volume>0 else None
        out.append(_factor("I06",security_id,cutoff,{"vwap_proxy":vwap,"distance_to_vwap_atr":(p-vwap)/atr if vwap is not None else None,"persistence_ratio":None},(p-vwap)/atr if vwap is not None else None,"VALID" if vwap is not None else "MISSING","VWAP_PROXY_UNAVAILABLE" if vwap is None else None,1.0,asof,source_batch_ids))
        width=(high-low) if high is not None and low is not None else None; loc=(p-low)/width if width and width>0 else None; retreat=(high-p)/atr if high is not None else None
        out.append(_factor("I07",security_id,cutoff,{"location":loc,"retreat_atr":retreat,"high_asof":high,"low_asof":low},loc,"VALID" if loc is not None else "MISSING","INTRADAY_RANGE_UNAVAILABLE" if loc is None else None,1.0,asof,source_batch_ids))
    return out

def rank_candidates(factor_values, quotes, limit=5, required_factor_ids=()):
    """Rank only securities with explicitly available eligibility factors.

    ``required_factor_ids`` lets the approved strategy enforce market/sector
    context separately from the per-security trend factors.
    """
    by={}; global_values={}
    for f in factor_values:
        if f.get("security_id"): by.setdefault(f["security_id"],{})[f["factor_id"]]=f
        else: global_values[f["factor_id"]]=f
    ranked=[]
    quote_map={q.get("security_id"):q for q in quotes}
    for sid,fs in by.items():
        quote=quote_map.get(sid,{})
        if quote.get("is_st") not in (False, 0): continue
        required=[fs.get(x) for x in ("I01","I02","I03","I04","I06")]
        required.extend(fs.get(x) or global_values.get(x) for x in required_factor_ids)
        if not all(x and x["validity"] == "VALID" for x in required): continue
        score=0.0; refs=[]; evidence=[]; risks=[]
        for fid in ("I01","I02","I03","I04","I06"):
            f=fs[fid]; refs.append(f"{fid}:{f['factor_version']}"); val=f.get("transformed_value")
            if isinstance(val,(int,float)): score += float(val)
            evidence.append(f"{fid} valid")
        r=fs.get("R01")
        if r and r.get("validity")=="VALID" and isinstance(r.get("transformed_value"),(int,float)) and r["transformed_value"]>3: risks.append("PRICE_EXTENDED")
        ranked.append({"security_id":sid,"score":score,"eligibility_status":"ELIGIBLE","strategy_ids":["baseline_daily_v0"],"evidence":evidence,"risks":risks,"factor_refs":refs})
    ranked.sort(key=lambda x:(-x["score"],x["security_id"]))
    for i,c in enumerate(ranked[:limit],1): c["rank"]=i
    return ranked[:limit]

def compute_market_daily_factors(quotes, history_by_security, cutoff, source_batch_ids=(), factor_version="0.1.0", data_asof=None):
    """Compute M03 using the same per-security daily history used by I02."""
    valid = 0; participating = 0; total = len(quotes)
    for q in quotes:
        sid=q.get("security_id"); rows=_history(history_by_security.get(sid,()))
        p=_num(q.get("last_price"))
        if len(rows) < 20 or p is None: continue
        valid += 1; participating += p > mean(r["close"] for r in rows[-20:])
    coverage=valid/total if total else 0.0
    return _factor("M03",None,cutoff,{"above_ma20_count":participating,"valid_count":valid,"total_count":total},participating/valid if valid else None,"VALID" if valid else "INSUFFICIENT_HISTORY","DAILY_HISTORY_REQUIRED" if not valid else None,coverage,data_asof,source_batch_ids,"趋势参与度")

def compute_limit_factor(limit_row, cutoff, source_batch_ids=(), factor_version="0.1.0", data_asof=None):
    """Compute M06 from a source-provided limit-statistics row; no inferred counts."""
    if not limit_row: return _factor("M06",None,cutoff,None,None,"MISSING","LIMIT_STATISTICS_REQUIRED",0.0,data_asof,source_batch_ids)
    def n(*keys):
        for k in keys:
            try:
                if limit_row.get(k) is not None: return int(limit_row[k])
            except (TypeError,ValueError): return None
        return None
    up=n("up_count","limit_up_count","limit_up_stock_count","rise_count"); down=n("down_count","limit_down_count","fall_count"); eligible=n("eligible_count","total_count","touched_limit_up_stock_count")
    opened=n("break_count","limit_break_count","open_stock_count")
    if up is None or eligible is None or eligible < 1:
        return _factor("M06",None,cutoff,{"up_count":up,"down_count":down,"open_count":opened,"eligible_count":eligible},None,"MISSING","LIMIT_STAT_FIELDS_INCOMPLETE",0.0,data_asof,source_batch_ids)
    raw={"up_count":up,"down_count":down,"open_count":opened,"eligible_count":eligible,"up_density":up/eligible,"open_rate":opened/eligible if opened is not None else None}
    transformed={"up_density":raw["up_density"],"open_rate":raw["open_rate"]}
    if down is not None: transformed["down_density"]=down/eligible; raw["down_density"]=down/eligible
    return _factor("M06",None,cutoff,raw,transformed,"VALID",None,1.0,data_asof,source_batch_ids,"涨停密度与开板率；不推断缺失的跌停数量")

def compute_sector_factors(quotes, history_by_security, memberships_by_index, index_histories, cutoff, source_batch_ids=(), factor_version="0.1.0", data_asof=None):
    """Compute S01/S02/S05 from fixed current membership and common daily rows.

    The result records current-membership usage in its explanation. It is usable
    for forward collection, but is not presented as historical membership replay.
    """
    qmap={q.get("security_id"):q for q in quotes}; returns={}; daily={}
    for sid,q in qmap.items():
        p=_num(q.get("last_price")); prev=_num(q.get("prev_close"))
        if p is not None and prev and prev>0: returns[sid]=p/prev-1
        rows=_history(history_by_security.get(sid,()))
        for i,r in enumerate(rows):
            prior=r.get("prev") or (rows[i-1]["close"] if i else None)
            if prior and prior>0: daily.setdefault(r["date"],{})[sid]=r["close"]/prior-1
    market=mean(returns.values()) if returns else None
    memberships={sid:[] for sid in qmap}
    for index_id,sids in memberships_by_index.items():
        for sid in sids:
            if sid in memberships: memberships[sid].append(index_id)
    all_dates=sorted(daily)
    out=[]
    for sid in qmap:
        ids=memberships.get(sid,[])
        if not ids:
            for fid in ("I01","S01","S02","S05"):
                out.append(_factor(fid,sid,cutoff,None,None,"MISSING","SECTOR_MEMBERSHIP_REQUIRED",0.0,data_asof,source_batch_ids))
            continue
        own_rows=_history(history_by_security.get(sid,()))
        own5=(own_rows[-1]["close"]/own_rows[-6]["close"]-1) if len(own_rows)>=6 and own_rows[-6]["close"] else None
        peer5_values=[]
        for index_id in ids:
            peers=[x for x in memberships_by_index.get(index_id,()) if x in qmap and x!=sid]
            for peer in peers:
                pr=_history(history_by_security.get(peer,()))
                if len(pr)>=6 and pr[-6]["close"]: peer5_values.append(pr[-1]["close"]/pr[-6]["close"]-1)
        i01=own5-mean(peer5_values) if own5 is not None and len(peer5_values) >= 5 else None
        out.append(_factor("I01",sid,cutoff,{"stock_return_5d":own5,"sector_return_5d":mean(peer5_values) if peer5_values else None,"membership_basis":"current_snapshot"},i01,"VALID" if i01 is not None else "MISSING","INDUSTRY_RETURN_INSUFFICIENT" if i01 is None else None,len(peer5_values)/max(1,len(ids)),data_asof,source_batch_ids,"当前成员快照；历史成员回放未确认"))
        s1=[]; s2=[]; s5=[]
        for index_id in ids:
            peers=[x for x in memberships_by_index.get(index_id,()) if x in qmap and x!=sid]
            peer_r=[returns[x] for x in peers if x in returns]
            if len(peer_r) >= 5 and market is not None: s1.append(mean(peer_r)-market)
            if len(peer_r) >= 5: s2.append(sum(x>0 for x in peer_r)/len(peer_r))
            relative_days=[]
            for d in all_dates[-5:]:
                peer_day=[daily[d][x] for x in peers if x in daily.get(d,{})]
                market_day=list(daily.get(d,{}).values())
                if len(peer_day)>=5 and len(market_day)>=30: relative_days.append(mean(peer_day)-mean(market_day))
            if len(relative_days)>=5 and len(peers) >= 5:
                s1.append(math.prod(1+x for x in relative_days)-1)
                s5.append(sum(x>0 for x in relative_days)/len(relative_days))
        out.append(_factor("S01",sid,cutoff,{"sector_count":len(ids),"relative_strength":mean(s1) if s1 else None,"membership_basis":"current_snapshot"},mean(s1) if s1 else None,"VALID" if s1 else "MISSING","SECTOR_RETURN_INSUFFICIENT" if not s1 else None,len(s1)/max(1,len(ids)),data_asof,source_batch_ids,"当前成员快照；历史成员回放未确认"))
        out.append(_factor("S02",sid,cutoff,{"sector_count":len(ids),"breadth_ex_self":mean(s2) if s2 else None},mean(s2) if s2 else None,"VALID" if s2 else "MISSING","SECTOR_QUOTE_INSUFFICIENT" if not s2 else None,len(s2)/max(1,len(ids)),data_asof,source_batch_ids))
        out.append(_factor("S05",sid,cutoff,{"sector_count":len(ids),"positive_relative_day_ratio":mean(s5) if s5 else None},mean(s5) if s5 else None,"VALID" if s5 else "MISSING","SECTOR_HISTORY_REQUIRED" if not s5 else None,len(s5)/max(1,len(ids)),data_asof,source_batch_ids,"当前成员快照；历史成员回放未确认"))
    return out


def build_rejections(factor_values, security_ids, required_factor_ids=(), global_values=None, quotes=()):
    by={}; globals_by=global_values or {f["factor_id"]:f for f in factor_values if not f.get("security_id")}; quote_map={q.get("security_id"):q for q in quotes}
    for f in factor_values:
        if f.get("security_id"): by.setdefault(f["security_id"],{})[f["factor_id"]]=f
    result=[]
    required=("I01","I02","I03","I04","I06")+tuple(required_factor_ids)
    for sid in security_ids:
        fs=by.get(sid,{})
        quote=quote_map.get(sid,{})
        if quote.get("is_st") in (True, 1):
            result.append({"security_id":sid,"reason_code":"ST_EXCLUDED","factor_refs":[],"details":{"is_st":True}}); continue
        if quote.get("is_st") not in (False, 0):
            result.append({"security_id":sid,"reason_code":"ST_STATUS_UNKNOWN","factor_refs":[],"details":{"is_st":quote.get("is_st")}}); continue
        missing=[]
        for fid in required:
            f=fs.get(fid) or globals_by.get(fid)
            if not f or f.get("validity") != "VALID": missing.append({"factor_id":fid,"reason":(f or {}).get("missing_reason","NOT_COMPUTED")})
        if missing: result.append({"security_id":sid,"reason_code":"REQUIRED_FACTOR_INVALID","factor_refs":[x["factor_id"] for x in missing],"details":{"missing":missing}})
    return result
