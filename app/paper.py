from __future__ import annotations

from dataclasses import dataclass

from .models import PaperFill, PaperQuote


@dataclass
class PaperMarketMaker:
    notional: float
    half_spread_bps: float
    requote_seconds: float
    bid: PaperQuote | None = None
    ask: PaperQuote | None = None

    def refresh(self, symbol: str, ts_ms: int, mid: float) -> None:
        if mid <= 0:
            return
        stale = self.bid is None or ts_ms - self.bid.created_ts_ms >= int(self.requote_seconds * 1000)
        if not stale:
            return
        qty = self.notional / mid
        half = self.half_spread_bps / 10000.0
        self.bid = PaperQuote(symbol, "BUY", mid * (1.0 - half), qty, ts_ms)
        self.ask = PaperQuote(symbol, "SELL", mid * (1.0 + half), qty, ts_ms)

    def on_trade(self, symbol: str, ts_ms: int, trade_price: float, mid: float) -> list[PaperFill]:
        fills: list[PaperFill] = []
        if self.bid and self.bid.symbol == symbol and trade_price <= self.bid.price:
            fills.append(PaperFill(ts_ms, symbol, "BUY", self.bid.price, self.bid.quantity, mid, "trade_through"))
            self.bid = None
        if self.ask and self.ask.symbol == symbol and trade_price >= self.ask.price:
            fills.append(PaperFill(ts_ms, symbol, "SELL", self.ask.price, self.ask.quantity, mid, "trade_through"))
            self.ask = None
        return fills
