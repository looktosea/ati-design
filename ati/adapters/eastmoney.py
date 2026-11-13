"""Eastmoney shadow adapter. It never produces formal ATI factors."""
from __future__ import annotations
import hashlib,json,time
from datetime import datetime,timezone
from pathlib import Path
from urllib.error import HTTPError,URLError
from urllib.parse import urlencode
from urllib.request import Request,urlopen
from .fuyao import RawBatch

class EastmoneyShadowError(RuntimeError): pass
class EastmoneyClient:
    source_name="eastmoney_shadow"
    def __init__(self, settings, raw_dir=None, opener=urlopen):
        self.settings=settings; self.raw_dir=Path(raw_dir or settings.raw_data_dir)/"shadow"; self.opener=opener
    def _request(self, host, endpoint, params):
        url=f"{host.rstrip('/')}/{endpoint.lstrip('/')}?{urlencode(params)}"; started=datetime.now(timezone.utc)
        try:
            req=Request(url,headers={"Accept":"application/json","User-Agent":"ATI-shadow/0.1"})
            with self.opener(req,timeout=float(getattr(self.settings,'eastmoney_timeout_seconds',15))) as response:
                payload=json.loads(response.read(50_000_000).decode('utf-8')); status=response.status
        except (HTTPError,URLError,TimeoutError,ValueError,json.JSONDecodeError) as exc: raise EastmoneyShadowError(f"shadow request failed: {type(exc).__name__}") from exc
        if not isinstance(payload,dict) or payload.get('rc') != 0: raise EastmoneyShadowError("shadow business response failed")
        received=datetime.now(timezone.utc); content=json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode(); digest=hashlib.sha256(content).hexdigest(); batch_id=f"shadow-{started.strftime('%Y%m%dT%H%M%S%fZ')}-{digest[:12]}"; path=self.raw_dir/datetime.now(timezone.utc).strftime('%Y/%m/%d')/f"{batch_id}.json"; path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(content)
        data=payload.get('data'); source_ts=None
        if isinstance(data,dict):
            value=data.get('timestamp')
            try: source_ts=datetime.fromtimestamp(float(value)/(1000 if float(value)>10_000_000_000 else 1),timezone.utc) if value is not None else None
            except (TypeError,ValueError,OverflowError): pass
        batch=RawBatch(batch_id,self.source_name,endpoint,None,started,received,'SUCCESS',digest,str(path),None,source_ts)
        return payload,batch
    def trends(self, secid, ndays=1):
        return self._request('https://push2.eastmoney.com','/api/qt/stock/trends2/get',{'secid':secid,'ut':'fa5fd1943c7b386f172d6893dbfba10b','ndays':ndays,'iscr':0,'fields1':'f1,f2,f3,f4,f5,f6','fields2':'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61'})
    def capital_flow(self, secid, limit=3):
        return self._request('https://push2.eastmoney.com','/api/qt/stock/fflow/kline/get',{'secid':secid,'ut':'fa5fd1943c7b386f172d6893dbfba10b','lmt':limit,'klt':1,'fields1':'f1,f2,f3,f4,f5,f6','fields2':'f51,f52,f53,f54,f55,f56,f57,f58'})
