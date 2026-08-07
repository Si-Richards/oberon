from __future__ import annotations

import asyncio
import logging
import os
import signal
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from .binance import BinanceAPIError, BinanceClient
from .config import Settings
from .models import BookTicker, OpenOrder, SymbolRules
from .paper import PaperBroker
from .state import StateStore
from .strategy import Strategy
from .util import bps_delta, now_ms

log = logging.getLogger("oberon")


def split_symbol(symbol: str) -> tuple[str, str]:
    quotes = ("USDT", "USDC", "FDUSD", "BTC", "ETH", "BNB")
    for quote in quotes:
        if symbol.endswith(quote) and len(symbol) > len(quote):
            return symbol[:-len(quote)], quote
    raise ValueError(f"Cannot infer base/quote assets for {symbol}")


class MarketMakerBot:
    def __init__(self, settings: Settings):
        self.s = settings
        self.store = StateStore(settings.database_path)
        self.stop = asyncio.Event()
        self.latest_book: BookTicker | None = None
        self.health_file = Path(os.getenv("HEALTH_FILE", "/tmp/oberon-health"))
        self.base_asset, self.quote_asset = split_symbol(settings.symbol)
        self.start_equity: Decimal | None = None

    async def run(self) -> None:
        log.info("starting mode=%s symbol=%s", self.s.trading_mode, self.s.symbol)
        async with BinanceClient(self.s) as market_client:
            rules = await market_client.symbol_rules(self.s.symbol)
            strategy = Strategy(self.s, rules)
            broker = market_client if self.s.is_testnet else PaperBroker(
                self.s.paper_base_balance, self.s.paper_quote_balance
            )

            if self.s.is_testnet:
                count = await broker.cancel_our_orders(self.s.symbol)
                log.info("startup cleanup canceled=%d", count)

            stream_task = asyncio.create_task(self._consume_market(market_client))
            try:
                await self._quote_loop(broker, strategy, rules)
            finally:
                stream_task.cancel()
                await asyncio.gather(stream_task, return_exceptions=True)
                if self.s.is_testnet:
                    try:
                        count = await broker.cancel_our_orders(self.s.symbol)
                        log.info("shutdown cleanup canceled=%d", count)
                    except Exception as exc:
                        log.error("shutdown cleanup failed: %s", exc)
                self.store.close()

    async def _consume_market(self, client: BinanceClient) -> None:
        async for book in client.book_ticker_stream(self.s.symbol):
            self.latest_book = book

    async def _quote_loop(self, broker, strategy: Strategy, rules: SymbolRules) -> None:
        while not self.stop.is_set():
            await asyncio.sleep(self.s.refresh_interval_ms / 1000)
            self.health_file.touch()
            book = self.latest_book
            if book is None:
                continue
            age = now_ms() - book.received_ms
            if age > self.s.stale_market_data_ms:
                log.warning("quotes disabled: market data stale age_ms=%d", age)
                await self._cancel_all(broker)
                continue

            base, quote = await broker.balances(self.base_asset, self.quote_asset)
            equity = base.total * book.mid + quote.total
            if self.start_equity is None:
                self.start_equity = equity
            pnl = equity - self.start_equity
            base_value = base.total * book.mid
            if pnl <= -self.s.max_daily_loss:
                log.error("kill switch: daily loss %.4f", pnl)
                await self._cancel_all(broker)
                continue
            if base_value > self.s.max_base_value:
                log.warning("inventory cap exceeded base_value=%s", base_value)

            vol = strategy.volatility_bps()
            if vol > self.s.max_volatility_bps:
                log.warning("quotes disabled: volatility=%.2fbps", vol)
                await self._cancel_all(broker)
                continue

            try:
                plan = strategy.plan(book, base, quote)
            except ValueError as exc:
                log.error("strategy configuration error: %s", exc)
                await self._cancel_all(broker)
                continue

            current = {o.side: o for o in await broker.open_orders(self.s.symbol)
                       if o.client_order_id.startswith("oberon-")}
            await self._maintain_side(broker, current.get("BUY"), "BUY", plan.bid_price, plan.bid_qty)
            await self._maintain_side(broker, current.get("SELL"), "SELL", plan.ask_price, plan.ask_qty)

            log.info(
                "mode=%s mid=%s vol=%.2f inv=%.1f%% equity=%.4f pnl=%.4f bid=%s ask=%s",
                self.s.trading_mode, book.mid, strategy.volatility_bps(),
                float(plan.inventory_ratio * 100), equity, pnl, plan.bid_price, plan.ask_price,
            )

    async def _maintain_side(self, broker, order: OpenOrder | None, side: str, price: Decimal, qty: Decimal) -> None:
        if side == "BUY" and self.latest_book and qty * price > Decimal("0"):
            pass
        replace = order is None
        if order is not None:
            age = (now_ms() - order.created_ms) / 1000
            replace = age >= self.s.order_ttl_seconds or bps_delta(order.price, price) >= self.s.requote_threshold_bps
        if not replace:
            return
        if order is not None:
            await broker.cancel_order(self.s.symbol, order.order_id)
        client_id = f"oberon-{side.lower()}-{uuid4().hex[:16]}"
        try:
            result = await broker.place_maker(self.s.symbol, side, qty, price, client_id)
            self.store.upsert_order(result)
            log.info("order placed side=%s price=%s qty=%s id=%s", side, price, qty, result["orderId"])
        except BinanceAPIError as exc:
            if exc.code in {-2010, -1013}:
                log.warning("order rejected side=%s: %s", side, exc)
                self.store.event("order_rejected", {"side": side, "error": str(exc)})
                return
            raise

    async def _cancel_all(self, broker) -> None:
        for order in await broker.open_orders(self.s.symbol):
            if order.client_order_id.startswith("oberon-"):
                await broker.cancel_order(self.s.symbol, order.order_id)


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


async def async_main() -> None:
    settings = Settings()
    configure_logging(settings.log_level)
    bot = MarketMakerBot(settings)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, bot.stop.set)
    await bot.run()


if __name__ == "__main__":
    asyncio.run(async_main())
