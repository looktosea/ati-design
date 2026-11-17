"""Fuyao REST adapter and supplier-neutral response normalization."""
from __future__ import annotations
import hashlib, json, random, time as clock
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

class FuyaoError(RuntimeError): pass
class FuyaoAuthError(FuyaoError): pass
class FuyaoBusinessError(FuyaoError): pass
class FuyaoTransportError(FuyaoError): pass

@dataclass(frozen=True)
class ApiEnvelope:
    code: int
    message: str
    data: Any
    request_id: str | None
    received_at: datetime
    source_timestamp: datetime | None
    raw: dict[str, Any]

@dataclass(frozen=True)
class RawBatch:
    batch_id: str
    source_name: str
    endpoint: str
    request_id: str | None
    requested_at: datetime
    received_at: datetime
    status: str
    content_sha256: str
    raw_uri: str
    item_count: int | None
    source_timestamp: datetime | None


def _ts(value: Any) -> datetime | None:
    if value is None: return None
    try:
        n = float(value); n = n / 1000 if n > 10_000_000_000 else n
        return datetime.fromtimestamp(n, timezone.utc)
    except (TypeError, ValueError, OverflowError): return None

def parse_response(payload: Any, received_at: datetime | None = None) -> ApiEnvelope:
    """Parse the Fuyao ApiResponse envelope without exposing request credentials."""
    if not isinstance(payload, dict): raise FuyaoBusinessError("Fuyao response is not an object")
    code = payload.get("code")
    if code != 0: raise FuyaoBusinessError(f"Fuyao business error code={code}")
    data = payload.get("data")
    source_value = (data or {}).get("timestamp") if isinstance(data, dict) else payload.get("timestamp")
    received = received_at or datetime.now(timezone.utc)
    return ApiEnvelope(int(code), str(payload.get("message", "success")), data, payload.get("request_id"), received, _ts(source_value), payload)

def _epoch_ms(value: Any) -> int | None:
    if value is None: return None
    if isinstance(value, (int, float)): return int(value)
    text=str(value).strip()
    if text.isdigit(): return int(text)
    try:
        from datetime import date
        parsed=datetime.fromisoformat(text.replace("Z","+00:00"))
        if parsed.tzinfo is None: parsed=parsed.replace(tzinfo=timezone.utc)
        return int(parsed.timestamp()*1000)
    except ValueError:
        try: return int(datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()*1000)
        except ValueError as exc: raise ValueError(f"invalid date/time: {value}") from exc

def _items(data: Any) -> list[Any]:
    if isinstance(data, list): return data
    if isinstance(data, dict):
        for key in ("items", "item", "rows", "results", "data"):
            if isinstance(data.get(key), list): return data[key]
    return []

class FuyaoClient:
    def __init__(self, settings, raw_dir: str | Path | None = None, opener=urlopen):
        self.settings = settings; self.raw_dir = Path(raw_dir or settings.raw_data_dir); self.opener = opener
        if not settings.fuyao_api_key: raise FuyaoAuthError("FUYAO_API_KEY is not set")

    def _url(self, endpoint: str, params: dict[str, Any] | None) -> str:
        return f"{self.settings.fuyao_base_url}/{endpoint.lstrip('/')}" + (("?" + urlencode(params)) if params else "")

    def request(self, endpoint: str, params: dict[str, Any] | None = None) -> ApiEnvelope:
        requested = datetime.now(timezone.utc); url = self._url(endpoint, params)
        request = Request(url, headers={"X-api-key": self.settings.fuyao_api_key, "Accept": "application/json", "User-Agent": "ATI/0.1"})
        last: Exception | None = None
        for attempt in range(self.settings.fuyao_max_retries + 1):
            try:
                with self.opener(request, timeout=self.settings.fuyao_timeout_seconds) as response:
                    body = response.read(50_000_000); payload = json.loads(body.decode("utf-8")); status = response.status
                break
            except HTTPError as exc:
                last = exc
                if exc.code in (401, 403): raise FuyaoAuthError(f"Fuyao authentication failed (HTTP {exc.code})") from exc
                if exc.code not in (408, 425, 429, 500, 502, 503, 504): raise FuyaoTransportError(f"Fuyao HTTP {exc.code}") from exc
            except (URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError) as exc:
                last = exc
            if attempt < self.settings.fuyao_max_retries:
                clock.sleep(max(self.settings.fuyao_request_gap_seconds, 0.05) * (2 ** attempt) + random.random() * .05)
        else: raise FuyaoTransportError("Fuyao request failed after retries") from last
        return parse_response(payload, datetime.now(timezone.utc))

    def request_and_save(self, endpoint, params=None) -> tuple[ApiEnvelope, RawBatch]:
        started = datetime.now(timezone.utc); envelope = self.request(endpoint, params)
        content = json.dumps(envelope.raw, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        digest = hashlib.sha256(content).hexdigest(); batch_id = f"fuyao-{started.strftime('%Y%m%dT%H%M%S%fZ')}-{digest[:12]}"
        path = self.raw_dir / datetime.now(timezone.utc).strftime("%Y/%m/%d") / f"{batch_id}.json"; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        rows = _items(envelope.data)
        batch = RawBatch(batch_id, "fuyao", endpoint, envelope.request_id, started, envelope.received_at, "SUCCESS", digest, str(path), len(rows), envelope.source_timestamp)
        return envelope, batch

    def current_a_shares(self, limit=1000, offset=0):
        return self.request_and_save("/api/meta/tickers/list", {"asset_type":"a-share", "limit":limit, "offset":offset})

    def current_a_shares_all(self, page_size=1000, max_pages=100):
        """Fetch every page of the A-share universe and retain each raw page."""
        if page_size <= 0 or max_pages <= 0: raise ValueError("page_size and max_pages must be positive")
        pages=[]; offset=0
        for _ in range(max_pages):
            envelope, batch = self.current_a_shares(page_size, offset)
            pages.append((envelope, batch)); rows=_items(envelope.data)
            total = (envelope.data or {}).get("total") if isinstance(envelope.data, dict) else None
            offset += len(rows)
            if not rows or (total is not None and offset >= int(total)) or len(rows) < page_size: break
        else:
            raise FuyaoTransportError("universe pagination exceeded max_pages")
        return pages

    def market_snapshot(self, limit=10000, offset=0):
        return self.request_and_save("/api/a-share/prices/snapshot", {"limit":limit,"offset":offset})

    def market_snapshot_all(self, page_size=10000, max_pages=100):
        if page_size <= 0 or max_pages <= 0: raise ValueError("page_size and max_pages must be positive")
        pages=[]; offset=0
        for _ in range(max_pages):
            envelope,batch=self.market_snapshot(page_size,offset); pages.append((envelope,batch)); rows=_items(envelope.data)
            total=(envelope.data or {}).get("total") if isinstance(envelope.data,dict) else None; offset += len(rows)
            if not rows or (total is not None and offset >= int(total)) or len(rows) < page_size: break
        else: raise FuyaoTransportError("market snapshot pagination exceeded max_pages")
        return pages
    def trading_days(self, start=None, end=None):
        p = {}
        if start: p["start_date"] = start
        if end: p["end_date"] = end
        return self.request_and_save("/api/a-share/calendar/trading-days", p)

    def index_catalog(self, kind="cn_concept"):
        tags={"ths":"cn_concept","concept":"cn_concept","industry":"industry","region":"region","tszs":"tszs"}
        return self.request_and_save("/api/a-share-index/catalog/ths-index-list", {"tag":tags.get(kind,kind)})

    def index_members(self, index_id):
        return self.request_and_save("/api/a-share-index/constituents/ths-stock-list", {"thscode": index_id})

    def indexes_for_security(self, security_id):
        return self.request_and_save("/api/a-share-index/constituents/ths-index-list-by-stock", {"thscode": security_id})

    def index_snapshot(self, index_ids):
        ids = list(index_ids)
        if not ids: raise ValueError("index_ids cannot be empty")
        return self.request_and_save("/api/a-share-index/prices/snapshot", {"thscodes": ",".join(ids)})

    def index_daily_history(self, index_id, start=None, end=None):
        if start is None or end is None: raise ValueError("index history requires start and end")
        p={"thscode":index_id,"interval":"1d","start":_epoch_ms(start),"end":_epoch_ms(end)}
        return self.request_and_save("/api/a-share-index/prices/historical",p)

    def limit_statistics(self, trade_date=None):
        p = {"date": trade_date} if trade_date else {}
        return self.request_and_save("/api/a-share/special-data/limit-up-statistics", p)

    def daily_history(self, thscode, start=None, end=None, adjust="forward"):
        if start is None or end is None: raise ValueError("stock history requires start and end")
        p = {"thscode": thscode, "interval": "1d", "start": _epoch_ms(start), "end": _epoch_ms(end), "adjust": adjust}
        return self.request_and_save("/api/a-share/prices/historical", p)

    def daily_history_batch(self, thscodes, start=None, end=None, adjust="forward"):
        """Fetch up to ten securities through Fuyao's native historical-batch endpoint."""
        codes = list(thscodes)
        if not codes or len(codes) > 10: raise ValueError("history import batches at most 10 securities")
        params={"thscodes": ",".join(codes), "interval":"1d", "start":_epoch_ms(start), "end":_epoch_ms(end), "adjust":adjust}
        return self.request_and_save("/api/a-share/prices/historical-batch", params)
