from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _float(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


def _symbols(raw: str) -> tuple[str, ...]:
    out = tuple(dict.fromkeys(s.strip().upper() for s in raw.split(",") if s.strip()))
    if not out:
        raise ValueError("SYMBOLS must contain at least one symbol")
    return out


@dataclass(frozen=True)
class Settings:
    version: str = "0.9.1"
    symbols: tuple[str, ...] = _symbols(os.getenv("SYMBOLS", "BTCUSDT,ETHUSDT,SOLUSDT"))
    data_dir: Path = Path(os.getenv("OBERON_DATA_DIR", "/data"))
    market_dir_name: str = os.getenv("MARKET_DIR_NAME", "markets-v091")
    ws_base_url: str = os.getenv("FUTURES_WS_BASE_URL", "wss://fstream.binance.com")
    rest_base_url: str = os.getenv("FUTURES_REST_BASE_URL", "https://fapi.binance.com")
    sample_interval_ms: int = _int("SAMPLE_INTERVAL_MS", 1000)
    depth_levels: int = _int("DEPTH_LEVELS", 20)
    sqlite_commit_every: int = _int("SQLITE_COMMIT_EVERY", 25)
    sqlite_busy_timeout_ms: int = _int("SQLITE_BUSY_TIMEOUT_MS", 5000)
    stale_market_ms: int = _int("STALE_MARKET_MS", 5000)
    paper_enabled: bool = _bool("PAPER_ENABLED", False)
    paper_notional: float = _float("PAPER_NOTIONAL", 25.0)
    paper_half_spread_bps: float = _float("PAPER_HALF_SPREAD_BPS", 8.0)
    paper_requote_seconds: float = _float("PAPER_REQUOTE_SECONDS", 5.0)
    research_only: bool = _bool("RESEARCH_ONLY", True)

    @property
    def market_dir(self) -> Path:
        return self.data_dir / self.market_dir_name

    def validate(self) -> None:
        if self.sample_interval_ms < 100:
            raise ValueError("SAMPLE_INTERVAL_MS must be >= 100")
        if self.depth_levels not in {5, 10, 20}:
            raise ValueError("DEPTH_LEVELS must be one of 5, 10, 20")
        if not self.ws_base_url.startswith("wss://"):
            raise ValueError("FUTURES_WS_BASE_URL must use wss://")
        if self.paper_enabled and not self.research_only:
            raise ValueError("v0.9.1 intentionally supports research/paper only; RESEARCH_ONLY must remain true")


def load_settings() -> Settings:
    s = Settings()
    s.validate()
    s.market_dir.mkdir(parents=True, exist_ok=True)
    return s
