from __future__ import annotations

import math
import statistics
from collections import deque
from dataclasses import dataclass, field
from typing import Deque


def bps_ratio(a: float, b: float) -> float:
    if b <= 0:
        return 0.0
    return (a / b - 1.0) * 10000.0


def imbalance(bids: list[tuple[float, float]], asks: list[tuple[float, float]], levels: int) -> float:
    b = sum(q for _, q in bids[:levels])
    a = sum(q for _, q in asks[:levels])
    total = b + a
    return 0.0 if total <= 0 else (b - a) / total


def depth_notional(levels: list[tuple[float, float]], n: int) -> float:
    return sum(px * qty for px, qty in levels[:n])


def microprice(bid: float, bid_qty: float, ask: float, ask_qty: float) -> float:
    total = bid_qty + ask_qty
    if total <= 0:
        return (bid + ask) / 2.0
    return (ask * bid_qty + bid * ask_qty) / total


@dataclass
class Trade:
    ts_ms: int
    signed_quote: float


@dataclass
class PricePoint:
    ts_ms: int
    mid: float


@dataclass
class FeatureEngine:
    trades: Deque[Trade] = field(default_factory=lambda: deque(maxlen=100_000))
    prices: Deque[PricePoint] = field(default_factory=lambda: deque(maxlen=20_000))

    def on_trade(self, ts_ms: int, price: float, qty: float, buyer_is_maker: bool) -> None:
        signed = price * qty * (-1.0 if buyer_is_maker else 1.0)
        self.trades.append(Trade(ts_ms, signed))
        self._trim(ts_ms)

    def on_mid(self, ts_ms: int, mid: float) -> None:
        if mid > 0:
            if not self.prices or ts_ms > self.prices[-1].ts_ms:
                self.prices.append(PricePoint(ts_ms, mid))
            elif ts_ms == self.prices[-1].ts_ms:
                self.prices[-1] = PricePoint(ts_ms, mid)
        self._trim(ts_ms)

    def _trim(self, now_ms: int) -> None:
        while self.trades and self.trades[0].ts_ms < now_ms - 180_000:
            self.trades.popleft()
        while self.prices and self.prices[0].ts_ms < now_ms - 180_000:
            self.prices.popleft()

    def trade_flow(self, now_ms: int, seconds: int) -> float:
        cutoff = now_ms - seconds * 1000
        vals = [t.signed_quote for t in self.trades if t.ts_ms >= cutoff]
        total = sum(abs(v) for v in vals)
        return 0.0 if total <= 0 else sum(vals) / total

    def past_return_bps(self, now_ms: int, seconds: int, current_mid: float) -> float:
        target = now_ms - seconds * 1000
        prior = None
        for p in reversed(self.prices):
            if p.ts_ms <= target:
                prior = p
                break
        return 0.0 if prior is None else bps_ratio(current_mid, prior.mid)

    def realised_vol_bps(self, now_ms: int, seconds: int = 60) -> float:
        cutoff = now_ms - seconds * 1000
        pts = [p for p in self.prices if p.ts_ms >= cutoff]
        if len(pts) < 5:
            return 0.0
        rets = [math.log(pts[i].mid / pts[i-1].mid) * 10000.0 for i in range(1, len(pts)) if pts[i-1].mid > 0]
        return statistics.pstdev(rets) if len(rets) >= 2 else 0.0
