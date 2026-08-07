from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
from decimal import Decimal
from urllib.parse import urlencode

import aiohttp

from .config import Settings
from .models import Balance, BookTicker, OpenOrder, SymbolRules
from .util import now_ms

log = logging.getLogger(__name__)


class BinanceAPIError(RuntimeError):
    def __init__(self, status: int, payload: object):
        self.status = status
        self.payload = payload
        self.code = payload.get("code") if isinstance(payload, dict) else None
        self.message = payload.get("msg") if isinstance(payload, dict) else str(payload)
        super().__init__(f"Binance HTTP {status}: code={self.code} msg={self.message}")


class BinanceClient:
    def __init__(self, settings: Settings):
        self.s = settings
        self.session: aiohttp.ClientSession | None = None
        self.server_offset_ms = 0

    async def __aenter__(self) -> "BinanceClient":
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10))
        await self.sync_time()
        return self

    async def __aexit__(self, *_: object) -> None:
        if self.session:
            await self.session.close()

    def _session(self) -> aiohttp.ClientSession:
        if self.session is None:
            raise RuntimeError("client not started")
        return self.session

    async def public_get(self, path: str, params: dict | None = None) -> object:
        async with self._session().get(self.s.rest_base_url + path, params=params) as r:
            payload = await r.json(content_type=None)
            if r.status >= 400:
                raise BinanceAPIError(r.status, payload)
            return payload

    async def signed_request(self, method: str, path: str, params: dict | None = None) -> object:
        params = dict(params or {})
        params["timestamp"] = now_ms() + self.server_offset_ms
        params["recvWindow"] = self.s.recv_window_ms
        query = urlencode(params)
        signature = hmac.new(
            self.s.binance_api_secret.encode(), query.encode(), hashlib.sha256
        ).hexdigest()
        headers = {"X-MBX-APIKEY": self.s.binance_api_key}
        url = f"{self.s.rest_base_url}{path}?{query}&signature={signature}"
        async with self._session().request(method, url, headers=headers) as r:
            payload = await r.json(content_type=None)
            if r.status >= 400:
                raise BinanceAPIError(r.status, payload)
            return payload

    async def sync_time(self) -> None:
        payload = await self.public_get("/api/v3/time")
        self.server_offset_ms = int(payload["serverTime"]) - now_ms()
        log.info("Binance clock offset=%dms", self.server_offset_ms)

    async def symbol_rules(self, symbol: str) -> SymbolRules:
        payload = await self.public_get("/api/v3/exchangeInfo", {"symbol": symbol})
        item = payload["symbols"][0]
        filters = {f["filterType"]: f for f in item["filters"]}
        notional = filters.get("NOTIONAL") or filters.get("MIN_NOTIONAL") or {}
        return SymbolRules(
            tick_size=Decimal(filters["PRICE_FILTER"]["tickSize"]),
            step_size=Decimal(filters["LOT_SIZE"]["stepSize"]),
            min_qty=Decimal(filters["LOT_SIZE"]["minQty"]),
            min_notional=Decimal(notional.get("minNotional", "0")),
        )

    async def balances(self, base: str, quote: str) -> tuple[Balance, Balance]:
        payload = await self.signed_request("GET", "/api/v3/account")
        items = {b["asset"]: b for b in payload["balances"]}
        def one(asset: str) -> Balance:
            b = items.get(asset, {"free": "0", "locked": "0"})
            return Balance(Decimal(b["free"]), Decimal(b["locked"]))
        return one(base), one(quote)

    async def open_orders(self, symbol: str) -> list[OpenOrder]:
        payload = await self.signed_request("GET", "/api/v3/openOrders", {"symbol": symbol})
        return [
            OpenOrder(
                side=o["side"], order_id=int(o["orderId"]), client_order_id=o["clientOrderId"],
                price=Decimal(o["price"]), orig_qty=Decimal(o["origQty"]),
                executed_qty=Decimal(o["executedQty"]), status=o["status"],
                created_ms=int(o["time"]),
            )
            for o in payload
        ]

    async def place_maker(self, symbol: str, side: str, qty: Decimal, price: Decimal, client_id: str) -> dict:
        payload = await self.signed_request(
            "POST", "/api/v3/order",
            {
                "symbol": symbol,
                "side": side,
                "type": "LIMIT_MAKER",
                "quantity": format(qty, "f"),
                "price": format(price, "f"),
                "newClientOrderId": client_id,
                "newOrderRespType": "RESULT",
            },
        )
        return dict(payload)

    async def cancel_order(self, symbol: str, order_id: int) -> dict | None:
        try:
            payload = await self.signed_request(
                "DELETE", "/api/v3/order", {"symbol": symbol, "orderId": order_id}
            )
            return dict(payload)
        except BinanceAPIError as exc:
            if exc.code in {-2011, -2013}:
                return None
            raise

    async def cancel_our_orders(self, symbol: str, prefix: str = "oberon-") -> int:
        count = 0
        for order in await self.open_orders(symbol):
            if order.client_order_id.startswith(prefix):
                await self.cancel_order(symbol, order.order_id)
                count += 1
        return count

    async def book_ticker_stream(self, symbol: str):
        stream = f"{symbol.lower()}@bookTicker"
        url = f"{self.s.ws_base_url.rstrip('/')}/{stream}"
        backoff = 1
        while True:
            try:
                async with self._session().ws_connect(url, heartbeat=20, autoping=True) as ws:
                    log.info("market WebSocket connected stream=%s", stream)
                    backoff = 1
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            data = json.loads(msg.data)
                            yield BookTicker(
                                bid=Decimal(data["b"]), bid_qty=Decimal(data["B"]),
                                ask=Decimal(data["a"]), ask_qty=Decimal(data["A"]),
                                event_ms=int(data.get("E", now_ms())), received_ms=now_ms(),
                            )
                        elif msg.type in {aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR}:
                            break
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("market WebSocket error: %s", exc)
            log.warning("market WebSocket reconnecting in %ss", backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)
