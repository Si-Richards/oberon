from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(slots=True)
class BookTicker:
    bid: Decimal
    bid_qty: Decimal
    ask: Decimal
    ask_qty: Decimal
    event_ms: int
    received_ms: int

    @property
    def mid(self) -> Decimal:
        return (self.bid + self.ask) / Decimal("2")


@dataclass(slots=True)
class SymbolRules:
    tick_size: Decimal
    step_size: Decimal
    min_qty: Decimal
    min_notional: Decimal


@dataclass(slots=True)
class Balance:
    free: Decimal
    locked: Decimal = Decimal("0")

    @property
    def total(self) -> Decimal:
        return self.free + self.locked


@dataclass(slots=True)
class QuotePlan:
    bid_price: Decimal
    ask_price: Decimal
    bid_qty: Decimal
    ask_qty: Decimal
    half_spread_bps: Decimal
    inventory_ratio: Decimal


@dataclass(slots=True)
class OpenOrder:
    side: str
    order_id: int
    client_order_id: str
    price: Decimal
    orig_qty: Decimal
    executed_qty: Decimal
    status: str
    created_ms: int
