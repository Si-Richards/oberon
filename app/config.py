from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")

    trading_mode: str = "paper"
    binance_api_key: str = ""
    binance_api_secret: str = ""
    symbol: str = "BTCUSDT"
    rest_base_url: str = "https://testnet.binance.vision"
    ws_base_url: str = "wss://stream.testnet.binance.vision/ws"
    database_path: Path = Path("/data/oberon.db")

    order_notional: Decimal = Decimal("10")
    base_half_spread_bps: Decimal = Decimal("12")
    min_half_spread_bps: Decimal = Decimal("8")
    max_half_spread_bps: Decimal = Decimal("40")
    inventory_skew_bps: Decimal = Decimal("12")
    target_base_value_percent: Decimal = Decimal("50")

    refresh_interval_ms: int = 1000
    requote_threshold_bps: Decimal = Decimal("2")
    order_ttl_seconds: int = 10
    stale_market_data_ms: int = 30000
    volatility_window_seconds: int = 30
    max_volatility_bps: Decimal = Decimal("60")
    max_base_value: Decimal = Decimal("200")
    max_daily_loss: Decimal = Decimal("25")
    recv_window_ms: int = Field(default=5000, ge=1000, le=60000)
    log_level: str = "INFO"

    paper_base_balance: Decimal = Decimal("0.001")
    paper_quote_balance: Decimal = Decimal("100")

    @property
    def is_testnet(self) -> bool:
        return self.trading_mode.lower() == "testnet"

    @property
    def is_paper(self) -> bool:
        return self.trading_mode.lower() == "paper"

    @model_validator(mode="after")
    def validate_safety(self) -> "Settings":
        mode = self.trading_mode.lower()
        if mode not in {"paper", "testnet"}:
            raise ValueError("TRADING_MODE must be paper or testnet; live mode is intentionally unsupported")
        if self.is_testnet:
            if not self.binance_api_key or not self.binance_api_secret:
                raise ValueError("Testnet mode requires BINANCE_API_KEY and BINANCE_API_SECRET")
            if "testnet.binance.vision" not in self.rest_base_url:
                raise ValueError("Testnet mode refuses non-testnet REST endpoint")
            if "testnet.binance.vision" not in self.ws_base_url:
                raise ValueError("Testnet mode refuses non-testnet WebSocket endpoint")
        return self
