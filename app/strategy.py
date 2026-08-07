from __future__ import annotations

from collections import deque
from decimal import Decimal

from .config import Settings
from .models import Balance, BookTicker, QuotePlan, SymbolRules
from .util import ceil_step, floor_step, now_ms


class Strategy:
    def __init__(self, settings: Settings, rules: SymbolRules):
        self.s = settings
        self.rules = rules
        self.prices: deque[tuple[int, Decimal]] = deque()

    def observe(self, book: BookTicker) -> None:
        cutoff = now_ms() - self.s.volatility_window_seconds * 1000
        self.prices.append((book.received_ms, book.mid))
        while self.prices and self.prices[0][0] < cutoff:
            self.prices.popleft()

    def volatility_bps(self) -> Decimal:
        if len(self.prices) < 2:
            return Decimal("0")
        prices = [p for _, p in self.prices]
        low, high = min(prices), max(prices)
        mid = prices[-1]
        return (high - low) / mid * Decimal("10000") if mid else Decimal("0")

    def plan(self, book: BookTicker, base: Balance, quote: Balance) -> QuotePlan:
        self.observe(book)
        mid = book.mid
        base_value = base.total * mid
        portfolio = base_value + quote.total
        inventory_ratio = base_value / portfolio if portfolio > 0 else Decimal("0")
        target = self.s.target_base_value_percent / Decimal("100")
        inventory_error = inventory_ratio - target

        vol = self.volatility_bps()
        half_spread = max(self.s.min_half_spread_bps, self.s.base_half_spread_bps + vol / 2)
        half_spread = min(self.s.max_half_spread_bps, half_spread)
        skew_bps = inventory_error * Decimal("2") * self.s.inventory_skew_bps
        reservation = mid * (Decimal("1") - skew_bps / Decimal("10000"))

        bid = reservation * (Decimal("1") - half_spread / Decimal("10000"))
        ask = reservation * (Decimal("1") + half_spread / Decimal("10000"))
        bid = floor_step(min(bid, book.ask - self.rules.tick_size), self.rules.tick_size)
        ask = ceil_step(max(ask, book.bid + self.rules.tick_size), self.rules.tick_size)

        raw_qty = self.s.order_notional / mid
        qty = floor_step(raw_qty, self.rules.step_size)
        if qty < self.rules.min_qty or qty * mid < self.rules.min_notional:
            raise ValueError("ORDER_NOTIONAL is below Binance minimum filters")
        return QuotePlan(bid, ask, qty, qty, half_spread, inventory_ratio)
