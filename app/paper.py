from __future__ import annotations

from decimal import Decimal

from .models import Balance, OpenOrder
from .util import now_ms


class PaperBroker:
    def __init__(self, base: Decimal, quote: Decimal):
        self.base = Balance(base)
        self.quote = Balance(quote)
        self.orders: dict[int, OpenOrder] = {}
        self._next = 1

    async def balances(self, *_: str) -> tuple[Balance, Balance]:
        return self.base, self.quote

    async def open_orders(self, _: str) -> list[OpenOrder]:
        return list(self.orders.values())

    async def place_maker(self, symbol: str, side: str, qty: Decimal, price: Decimal, client_id: str) -> dict:
        oid = self._next
        self._next += 1
        order = OpenOrder(side, oid, client_id, price, qty, Decimal("0"), "NEW", now_ms())
        self.orders[oid] = order
        return {"symbol": symbol, "orderId": oid, "clientOrderId": client_id, "side": side,
                "status": "NEW", "price": str(price), "origQty": str(qty), "executedQty": "0"}

    async def cancel_order(self, _: str, order_id: int) -> dict | None:
        order = self.orders.pop(order_id, None)
        return {"orderId": order_id, "status": "CANCELED"} if order else None

    async def cancel_our_orders(self, _: str, prefix: str = "oberon-") -> int:
        ids = [oid for oid, o in self.orders.items() if o.client_order_id.startswith(prefix)]
        for oid in ids:
            self.orders.pop(oid, None)
        return len(ids)
