"""Small dependency-free loader for the versioned factor registry."""
from __future__ import annotations
import re
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class FactorRegistry:
    version: str
    timezone: str
    factor_statuses: dict[str,str]

    def status(self, factor_id: str) -> str | None: return self.factor_statuses.get(factor_id)

def load_registry(path="config/factor_registry.yaml") -> FactorRegistry:
    text=Path(path).read_text(encoding="utf-8")
    version=re.search(r'^registry_version:\s*["\']?([^"\'\s]+)',text,re.M)
    timezone=re.search(r'^timezone:\s*([^\s]+)',text,re.M)
    if not version: raise ValueError("factor registry missing registry_version")
    statuses={}; current=None
    for line in text.splitlines():
        m=re.match(r'^  ([MSFIPR]\d{2}):\s*$',line)
        if m: current=m.group(1); continue
        m=re.match(r'^\s+status:\s*(ACTIVE|SHADOW|OBSERVE|UNAVAILABLE)\s*$',line)
        if m and current: statuses[current]=m.group(1)
    if not statuses: raise ValueError("factor registry has no factors")
    return FactorRegistry(version.group(1),timezone.group(1) if timezone else "Asia/Shanghai",statuses)
