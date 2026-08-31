from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

from .binance_futures import BinanceFuturesPublicStream
from .config import Settings
from .features import FeatureEngine, bps_ratio, depth_notional, imbalance, microprice
from .models import MarketSample
from .paper import PaperMarketMaker
from .state import SymbolStore

log = logging.getLogger(__name__)


@dataclass
class SymbolRuntime:
    features: FeatureEngine = field(default_factory=FeatureEngine)
    last_trade_price: float | None = None
    paper: PaperMarketMaker | None = None


class MarketCollector:
    def __init__(self, settings: Settings):
        self.s = settings
        self.stream = BinanceFuturesPublicStream(settings.ws_base_url, settings.symbols, settings.depth_levels)
        self.stop = asyncio.Event()
        self.runtime = {
            sym: SymbolRuntime(
                paper=PaperMarketMaker(
                    settings.paper_notional,
                    settings.paper_half_spread_bps,
                    settings.paper_requote_seconds,
                ) if settings.paper_enabled else None
            )
            for sym in settings.symbols
        }
        self.stores = {
            sym: SymbolStore(
                settings.market_dir / f"{sym.lower()}.db",
                settings.sqlite_commit_every,
                settings.sqlite_busy_timeout_ms,
            )
            for sym in settings.symbols
        }
        self.stream.on_trade(self._on_trade)

    def _on_trade(self, symbol: str, ts_ms: int, price: float, qty: float, buyer_is_maker: bool) -> None:
        rt = self.runtime[symbol]
        rt.last_trade_price = price
        rt.features.on_trade(ts_ms, price, qty, buyer_is_maker)
        book = self.stream.books[symbol]
        if rt.paper and book.bids and book.asks:
            mid = (book.bids[0][0] + book.asks[0][0]) / 2.0
            for fill in rt.paper.on_trade(symbol, ts_ms, price, mid):
                self.stores[symbol].insert_fill(fill)
                log.info("paper fill symbol=%s side=%s price=%.8f qty=%.8f", symbol, fill.side, fill.price, fill.quantity)

    async def run(self) -> None:
        stream_task = asyncio.create_task(self.stream.run_forever(self.stop), name="binance-public-stream")
        sample_task = asyncio.create_task(self._sample_loop(), name="sample-loop")
        try:
            await asyncio.gather(stream_task, sample_task)
        finally:
            self.stop.set()
            for store in self.stores.values():
                store.close()

    async def _sample_loop(self) -> None:
        interval = self.s.sample_interval_ms / 1000.0
        while not self.stop.is_set():
            started = time.monotonic()
            now_ms = int(time.time() * 1000)
            for symbol in self.s.symbols:
                try:
                    self._sample_symbol(symbol, now_ms)
                except Exception:
                    log.exception("sample failure symbol=%s", symbol)
            sleep_for = max(0.01, interval - (time.monotonic() - started))
            await asyncio.sleep(sleep_for)

    def _sample_symbol(self, symbol: str, now_ms: int) -> None:
        book = self.stream.books[symbol]
        if not book.bids or not book.asks:
            return
        if book.ts_ms and now_ms - book.ts_ms > self.s.stale_market_ms:
            return
        bid, bid_qty = book.bids[0]
        ask, ask_qty = book.asks[0]
        if bid <= 0 or ask <= bid:
            return
        mid = (bid + ask) / 2.0
        rt = self.runtime[symbol]
        rt.features.on_mid(now_ms, mid)
        mp = microprice(bid, bid_qty, ask, ask_qty)
        mark = self.stream.marks[symbol]
        sample = MarketSample(
            ts_ms=now_ms,
            symbol=symbol,
            bid=bid,
            ask=ask,
            mid=mid,
            spread_bps=(ask - bid) / mid * 10000.0,
            bid_depth_5=depth_notional(book.bids, 5),
            ask_depth_5=depth_notional(book.asks, 5),
            bid_depth_10=depth_notional(book.bids, 10),
            ask_depth_10=depth_notional(book.asks, 10),
            bid_depth_20=depth_notional(book.bids, 20),
            ask_depth_20=depth_notional(book.asks, 20),
            obi_l1=imbalance(book.bids, book.asks, 1),
            obi_l5=imbalance(book.bids, book.asks, 5),
            obi_l10=imbalance(book.bids, book.asks, 10),
            obi_l20=imbalance(book.bids, book.asks, 20),
            microprice=mp,
            microprice_bps=bps_ratio(mp, mid),
            trade_flow_5s=rt.features.trade_flow(now_ms, 5),
            trade_flow_30s=rt.features.trade_flow(now_ms, 30),
            trade_flow_60s=rt.features.trade_flow(now_ms, 60),
            ret_5s_bps=rt.features.past_return_bps(now_ms, 5, mid),
            ret_30s_bps=rt.features.past_return_bps(now_ms, 30, mid),
            ret_60s_bps=rt.features.past_return_bps(now_ms, 60, mid),
            vol_60s_bps=rt.features.realised_vol_bps(now_ms, 60),
            mark_price=mark.mark_price,
            index_price=mark.index_price,
            funding_rate=mark.funding_rate,
        )
        self.stores[symbol].insert_sample(sample)
        if rt.paper:
            rt.paper.refresh(symbol, now_ms, mid)
