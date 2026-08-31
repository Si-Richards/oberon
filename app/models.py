from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MarketSample:
    ts_ms: int
    symbol: str
    bid: float
    ask: float
    mid: float
    spread_bps: float
    bid_depth_5: float
    ask_depth_5: float
    bid_depth_10: float
    ask_depth_10: float
    bid_depth_20: float
    ask_depth_20: float
    obi_l1: float
    obi_l5: float
    obi_l10: float
    obi_l20: float
    microprice: float
    microprice_bps: float
    trade_flow_5s: float
    trade_flow_30s: float
    trade_flow_60s: float
    ret_5s_bps: float
    ret_30s_bps: float
    ret_60s_bps: float
    vol_60s_bps: float
    mark_price: float | None = None
    index_price: float | None = None
    funding_rate: float | None = None


@dataclass
class PaperQuote:
    symbol: str
    side: str
    price: float
    quantity: float
    created_ts_ms: int


@dataclass
class PaperFill:
    ts_ms: int
    symbol: str
    side: str
    price: float
    quantity: float
    mid_at_fill: float
    reason: str
