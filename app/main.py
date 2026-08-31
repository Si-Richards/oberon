from __future__ import annotations

import asyncio
import logging
import signal

from .collector import MarketCollector
from .config import load_settings


def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


async def amain() -> None:
    configure_logging()
    settings = load_settings()
    log = logging.getLogger("oberon")
    log.info(
        "starting Oberon v%s mode=%s symbols=%s data=%s",
        settings.version, "paper" if settings.paper_enabled else "research", ",".join(settings.symbols), settings.market_dir,
    )
    collector = MarketCollector(settings)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, collector.stop.set)
        except NotImplementedError:
            pass
    await collector.run()


def main() -> None:
    asyncio.run(amain())


if __name__ == "__main__":
    main()
