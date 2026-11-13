"""Data-quality gates used before a snapshot can become a valid signal."""
from __future__ import annotations
import json, os, re
from dataclasses import dataclass
from datetime import datetime, timezone

@dataclass(frozen=True)
class GateResult:
    status: str
    reasons: tuple[str, ...]
    coverage: float
    duplicate_count: int
    stale: bool


def evaluate_snapshot(rows, *, source_timestamp=None, received_at=None, expected_min=1, max_age_seconds=300) -> GateResult:
    reasons=[]; total=len(rows); ids=[]
    for r in rows:
        ids.append(str(r.get("security_id") or r.get("thscode") or r.get("ticker") or r.get("code") or ""))
    duplicate_count = total - len(set(ids))
    if total < expected_min: reasons.append("EMPTY_OR_INSUFFICIENT_ROWS")
    if duplicate_count: reasons.append("DUPLICATE_SECURITY_IDS")
    coverage = len({x for x in ids if x}) / total if total else 0.0
    if coverage < 1.0: reasons.append("MISSING_SECURITY_IDS")
    stale=False
    if source_timestamp:
        when = source_timestamp if source_timestamp.tzinfo else source_timestamp.replace(tzinfo=timezone.utc)
        received = received_at or datetime.now(timezone.utc)
        stale = (received - when).total_seconds() > max_age_seconds
        if stale: reasons.append("STALE_SOURCE_TIMESTAMP")
    return GateResult("BLOCKED" if reasons else "VALID", tuple(reasons), coverage, duplicate_count, stale)

def scan_secret_text(text: str) -> bool:
    """Return true when a likely API key is present; never emit the matched text."""
    return bool(re.search(r"(?i)(FUYAO_API_KEY\s*[=:]\s*|X-api-key\s*[:=]\s*)[^\s,;]+", text))

def assert_no_secret_in_artifacts(paths, secret: str | None = None):
    secret = secret or os.getenv("FUYAO_API_KEY", "")
    if not secret: return
    for path in paths:
        data = open(path, "rb").read()
        if secret.encode() in data: raise RuntimeError(f"secret found in artifact: {path}")
