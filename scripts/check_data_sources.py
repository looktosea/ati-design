#!/usr/bin/env python3
"""Read-only pre-development checks for ATI data sources.

The script deliberately does not write market data or print credentials. It only
checks authentication, response envelopes, basic field coverage and source
timestamps. Use it after copying .env.example to .env and exporting the values.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone


@dataclass
class CheckResult:
    name: str
    source: str
    ok: bool
    elapsed_ms: int
    status: int | None = None
    code: int | None = None
    message: str | None = None
    item_count: int | None = None
    timestamp: int | None = None
    fields: list[str] | None = None
    error: str | None = None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def query_url(base: str, path: str, params: dict[str, object]) -> str:
    encoded = urllib.parse.urlencode({k: str(v) for k, v in params.items()})
    return f"{base.rstrip('/')}{path}?{encoded}"


def call_json(
    name: str,
    source: str,
    url: str,
    headers: dict[str, str] | None = None,
    timeout: float = 20.0,
) -> CheckResult:
    started = time.monotonic()
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "ATI-preflight/0.1", **(headers or {})},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read(8_000_000).decode("utf-8"))
            status = response.status
        elapsed = int((time.monotonic() - started) * 1000)
    except urllib.error.HTTPError as exc:
        return CheckResult(
            name=name,
            source=source,
            ok=False,
            elapsed_ms=int((time.monotonic() - started) * 1000),
            status=exc.code,
            error=f"http_error:{exc.code}",
        )
    except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        return CheckResult(
            name=name,
            source=source,
            ok=False,
            elapsed_ms=int((time.monotonic() - started) * 1000),
            error=type(exc).__name__,
        )

    data = payload.get("data") if isinstance(payload, dict) else None
    rows: object = []
    fields: list[str] | None = None
    timestamp: int | None = None
    if isinstance(data, dict):
        timestamp = data.get("timestamp")
        rows = data.get("item", data.get("items", data.get("klines", [])))
        if isinstance(rows, list) and rows and isinstance(rows[0], dict):
            fields = sorted(str(key) for key in rows[0])

    business_code = payload.get("code") if isinstance(payload, dict) else None
    # Eastmoney uses rc rather than Fuyao's code.
    if source == "eastmoney":
        business_code = payload.get("rc") if isinstance(payload, dict) else None
        ok = business_code == 0
        message = "success" if ok else str(payload.get("msg", "business_error"))
    else:
        ok = business_code == 0 and status == 200
        message = str(payload.get("message", "business_error"))

    return CheckResult(
        name=name,
        source=source,
        ok=ok,
        elapsed_ms=elapsed,
        status=status,
        code=business_code,
        message=message[:160],
        item_count=len(rows) if isinstance(rows, list) else None,
        timestamp=timestamp,
        fields=fields,
    )


def fuyao_checks(base: str, key: str, full: bool, timeout: float) -> list[CheckResult]:
    headers = {"X-api-key": key}
    snapshot_limit = 10_000 if full else 5
    checks = [
        (
            "fuyao_universe",
            query_url(base, "/api/meta/tickers/list", {"asset_type": "a-share", "limit": 5, "offset": 0}),
        ),
        (
            "fuyao_snapshot",
            query_url(base, "/api/a-share/prices/snapshot", {"limit": snapshot_limit, "offset": 0}),
        ),
        ("fuyao_calendar", query_url(base, "/api/a-share/calendar/trading-days", {})),
        (
            "fuyao_index_snapshot",
            query_url(base, "/api/a-share-index/prices/snapshot", {"thscodes": "000001.SH,399001.SZ"}),
        ),
        (
            "fuyao_hot_hour",
            query_url(base, "/api/a-share/special-data/hot-stock-list", {"period": "hour", "limit": 5}),
        ),
        (
            "fuyao_stock_news",
            query_url(base, "/api/news/stock/timeline-list", {"thscode": "600519.SH", "offset": "first", "size": 1}),
        ),
    ]
    results: list[CheckResult] = []
    for name, url in checks:
        results.append(call_json(name, "fuyao", url, headers=headers, timeout=timeout))
        time.sleep(0.2)
    return results


def eastmoney_shadow_checks(timeout: float) -> list[CheckResult]:
    common = {
        "secid": "1.600519",
        "ut": "fa5fd1943c7b386f172d6893dbfba10b",
    }
    trends = query_url(
        "https://push2.eastmoney.com",
        "/api/qt/stock/trends2/get",
        {
            **common,
            "ndays": 1,
            "iscr": 0,
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        },
    )
    flow = query_url(
        "https://push2.eastmoney.com",
        "/api/qt/stock/fflow/kline/get",
        {
            **common,
            "lmt": 3,
            "klt": 1,
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58",
        },
    )
    return [
        call_json("eastmoney_trends_shadow", "eastmoney", trends, timeout=timeout),
        call_json("eastmoney_flow_shadow", "eastmoney", flow, timeout=timeout),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full", action="store_true", help="request the full Fuyao snapshot instead of a small page")
    parser.add_argument("--shadow", action="store_true", help="also probe Eastmoney shadow endpoints")
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    args = parser.parse_args()

    base = os.getenv("FUYAO_BASE_URL", "https://fuyao.aicubes.cn")
    key = os.getenv("FUYAO_API_KEY", "")
    if not key:
        print("FUYAO_API_KEY is not set; export it from a secret manager or .env", file=sys.stderr)
        return 2

    timeout = float(os.getenv("FUYAO_TIMEOUT_SECONDS", "20"))
    results = fuyao_checks(base, key, full=args.full, timeout=timeout)
    if args.shadow:
        results.extend(eastmoney_shadow_checks(timeout=timeout))

    if args.json:
        print(json.dumps({"checked_at": now_iso(), "results": [asdict(r) for r in results]}, ensure_ascii=False, indent=2))
    else:
        for result in results:
            state = "OK" if result.ok else "FAIL"
            details = []
            if result.code is not None:
                details.append(f"code={result.code}")
            if result.item_count is not None:
                details.append(f"items={result.item_count}")
            if result.timestamp is not None:
                details.append(f"timestamp={result.timestamp}")
            if result.error:
                details.append(result.error)
            print(f"{state:4} {result.source:10} {result.name:28} {result.elapsed_ms:5}ms {' '.join(details)}")

    return 0 if all(result.ok for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
