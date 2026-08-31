from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Awaitable, Callable

import aiohttp

log = logging.getLogger(__name__)


@dataclass
class BookState:
    ts_ms: int = 0
    bids: list[tuple[float, float]] = field(default_factory=list)
    asks: list[tuple[float, float]] = field(default_factory=list)


@dataclass
class MarkState:
    ts_ms: int = 0
    mark_price: float | None = None
    index_price: float | None = None
    funding_rate: float | None = None


class BinanceFuturesPublicStream:
    def __init__(self, ws_base_url: str, symbols: tuple[str, ...], depth_levels: int = 20):
        self.ws_base_url = ws_base_url.rstrip("/")
        self.symbols = symbols
        self.depth_levels = depth_levels
        self.books = {s: BookState() for s in symbols}
        self.marks = {s: MarkState() for s in symbols}
        self._trade_callbacks: list[Callable[[str, int, float, float, bool], Awaitable[None] | None]] = []

    def on_trade(self, cb: Callable[[str, int, float, float, bool], Awaitable[None] | None]) -> None:
        self._trade_callbacks.append(cb)

    def stream_url(self) -> str:
        streams: list[str] = []
        for symbol in self.symbols:
            s = symbol.lower()
            streams.extend([
                f"{s}@depth{self.depth_levels}@100ms",
                f"{s}@aggTrade",
                f"{s}@markPrice@1s",
            ])
        return f"{self.ws_base_url}/stream?streams={'/'.join(streams)}"

    async def run_forever(self, stop: asyncio.Event) -> None:
        backoff = 1.0
        timeout = aiohttp.ClientTimeout(total=None, sock_connect=15, sock_read=90)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            while not stop.is_set():
                try:
                    async with session.ws_connect(self.stream_url(), heartbeat=20, autoping=True, max_msg_size=2**22) as ws:
                        log.info("Binance Futures public WebSocket connected symbols=%s", ",".join(self.symbols))
                        backoff = 1.0
                        async for msg in ws:
                            if stop.is_set():
                                break
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                self._handle(json.loads(msg.data))
                            elif msg.type in {aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSE}:
                                break
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    log.warning("market WebSocket error: %s", exc)
                if stop.is_set():
                    break
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2.0, 30.0)

    def _handle(self, envelope: dict) -> None:
        data = envelope.get("data", envelope)
        event = data.get("e")
        symbol = str(data.get("s", "")).upper()
        if symbol not in self.books:
            return
        if event == "depthUpdate" or ("b" in data and "a" in data and event is None):
            raw_bids = data.get("bids", data.get("b", []))
            raw_asks = data.get("asks", data.get("a", []))
            bids = [(float(px), float(q)) for px, q in raw_bids if float(q) > 0]
            asks = [(float(px), float(q)) for px, q in raw_asks if float(q) > 0]
            if bids and asks:
                bids.sort(key=lambda x: x[0], reverse=True)
                asks.sort(key=lambda x: x[0])
                self.books[symbol] = BookState(int(data.get("E", data.get("T", 0))), bids, asks)
        elif event == "aggTrade":
            ts_ms = int(data.get("T", data.get("E", 0)))
            price = float(data["p"])
            qty = float(data["q"])
            buyer_is_maker = bool(data.get("m", False))
            for cb in self._trade_callbacks:
                result = cb(symbol, ts_ms, price, qty, buyer_is_maker)
                if asyncio.iscoroutine(result):
                    asyncio.create_task(result)
        elif event == "markPriceUpdate":
            self.marks[symbol] = MarkState(
                int(data.get("E", 0)), float(data["p"]), float(data["i"]), float(data["r"])
            )
