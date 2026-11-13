"""Runtime configuration. Secrets are read only from process environment."""
from __future__ import annotations
import os
from dataclasses import dataclass, field
from datetime import time
from zoneinfo import ZoneInfo

class ConfigError(ValueError): pass

def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}

def _float(name: str, default: float) -> float:
    try: return float(os.getenv(name, str(default)))
    except ValueError as exc: raise ConfigError(f"invalid {name}") from exc

def _int(name: str, default: int) -> int:
    try: return int(os.getenv(name, str(default)))
    except ValueError as exc: raise ConfigError(f"invalid {name}") from exc

@dataclass(frozen=True)
class Settings:
    timezone_name: str
    environment: str
    log_level: str
    fuyao_base_url: str
    fuyao_api_key: str = field(repr=False)
    fuyao_timeout_seconds: float
    fuyao_max_retries: int
    fuyao_request_gap_seconds: float
    database_url: str
    raw_data_dir: str
    signal_times: tuple[time, ...]
    max_candidates: int
    primary_horizon: int
    aux_horizons: tuple[int, ...]
    eastmoney_shadow_enabled: bool
    eastmoney_timeout_seconds: float
    eastmoney_request_gap_seconds: float

    @property
    def timezone(self) -> ZoneInfo: return ZoneInfo(self.timezone_name)

    def public(self) -> dict[str, object]:
        """Safe config for logs/diagnostics; deliberately excludes the API key."""
        return {"environment": self.environment, "timezone": self.timezone_name,
                "fuyao_base_url": self.fuyao_base_url, "database_url": self.database_url,
                "raw_data_dir": self.raw_data_dir, "signal_times": [t.isoformat() for t in self.signal_times],
                "max_candidates": self.max_candidates, "shadow_enabled": self.eastmoney_shadow_enabled}

def load_settings(environ: dict[str, str] | None = None) -> Settings:
    env = os.environ if environ is None else environ
    def get(k, default=""): return env.get(k, default)
    tz = get("ATI_SIGNAL_TIMEZONE", get("TZ", "Asia/Shanghai"))
    try: ZoneInfo(tz)
    except Exception as exc: raise ConfigError(f"invalid timezone: {tz}") from exc
    raw_times = [x.strip() for x in get("ATI_SIGNAL_TIMES", "14:30,14:35,14:40,14:45,14:50").split(",") if x.strip()]
    try: times = tuple(time.fromisoformat(x) for x in raw_times)
    except ValueError as exc: raise ConfigError("ATI_SIGNAL_TIMES must contain HH:MM values") from exc
    if not times: raise ConfigError("ATI_SIGNAL_TIMES cannot be empty")
    key = get("FUYAO_API_KEY", "")
    # Loading does not require a key for offline migration/quality commands. Network calls do.
    try:
        fuyao_timeout=float(get("FUYAO_TIMEOUT_SECONDS", "20")); retries=int(get("FUYAO_MAX_RETRIES", "3")); gap=float(get("FUYAO_REQUEST_GAP_SECONDS", "0.2")); max_candidates=int(get("ATI_MAX_CANDIDATES", "5")); primary=int(get("ATI_PRIMARY_HORIZON_TRADING_DAYS", "3")); aux=tuple(int(x) for x in get("ATI_AUX_HORIZONS", "1,5").split(",") if x); em_timeout=float(get("EASTMONEY_TIMEOUT_SECONDS", "15")); em_gap=float(get("EASTMONEY_REQUEST_GAP_SECONDS", "0.5"))
    except (TypeError,ValueError) as exc: raise ConfigError("invalid numeric ATI/Fuyao setting") from exc
    if fuyao_timeout <= 0 or retries < 0 or gap < 0 or max_candidates < 0 or primary <= 0 or any(x <= 0 for x in aux) or em_timeout <= 0 or em_gap < 0:
        raise ConfigError("ATI/Fuyao numeric settings out of range")
    return Settings(tz, get("ATI_ENV", "development"), get("ATI_LOG_LEVEL", "INFO"),
        get("FUYAO_BASE_URL", "https://fuyao.aicubes.cn").rstrip("/"), key,
        fuyao_timeout, retries, gap, get("ATI_DATABASE_URL", "sqlite:///data/ati.db"),
        get("ATI_RAW_DATA_DIR", "data/raw"), times, max_candidates, primary, aux,
        _bool_env(env, "EASTMONEY_SHADOW_ENABLED", False), em_timeout, em_gap)

def _bool_env(env, name, default): return env.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}
