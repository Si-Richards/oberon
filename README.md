# Oberon Market Maker

Oberon is a Binance Spot **Testnet / paper-trading** market-making research bot written in Python 3.12. Live Binance endpoints are deliberately rejected by configuration validation.

## What it does

- Streams `bookTicker` from Binance Spot Testnet.
- Places one post-only `LIMIT_MAKER` quote on each side.
- Adjusts spread with observed short-window volatility.
- Skews reservation price based on inventory imbalance.
- Requotes on TTL or material price movement.
- Reads Binance symbol filters and rounds price/quantity correctly.
- Reconciles open orders from Binance REST.
- Cancels only orders whose client IDs begin with `oberon-`.
- Persists orders/events in SQLite.
- Implements stale-market, volatility, inventory and daily-loss safety controls.
- Runs as a non-root Docker user with a persistent `/data` volume.

## Safety status

This repository is for engineering and strategy research. It supports only `paper` and `testnet` modes. It does **not** support production/live Binance trading.

## Quick start

```bash
cp .env.example .env
nano .env
docker compose up --build
```

Paper mode requires no keys. For Binance Spot Testnet:

```env
TRADING_MODE=testnet
BINANCE_API_KEY=...
BINANCE_API_SECRET=...
REST_BASE_URL=https://testnet.binance.vision
WS_BASE_URL=wss://stream.testnet.binance.vision/ws
```

Do not add `/api` to `REST_BASE_URL`; request paths already include `/api/v3/...`.

## First Testnet run

Use small settings initially:

```env
ORDER_NOTIONAL=10
STALE_MARKET_DATA_MS=30000
BASE_HALF_SPREAD_BPS=15
MIN_HALF_SPREAD_BPS=10
MAX_HALF_SPREAD_BPS=40
ORDER_TTL_SECONDS=10
MAX_BASE_VALUE=200
MAX_DAILY_LOSS=25
```

Start in the foreground:

```bash
docker compose up --build
```

Expected logs include:

```text
starting mode=testnet symbol=BTCUSDT
Binance clock offset=...
startup cleanup canceled=...
market WebSocket connected stream=btcusdt@bookTicker
order placed side=BUY ...
order placed side=SELL ...
```

Stop once with Ctrl+C and allow the grace period to cancel Oberon orders.

## Architecture

```text
Binance bookTicker WebSocket
          |
          v
   Market state / volatility
          |
          v
 Inventory-aware strategy
          |
          v
      Risk gates
          |
          v
 Order reconciliation / execution
          |
          +----> Binance Spot Testnet REST
          |
          +----> SQLite event/order state
```

## Database

Default path:

```text
/data/oberon.db
```

`StateStore` creates the parent directory before opening SQLite, avoiding the `sqlite3.OperationalError: unable to open database file` issue seen in the earlier prototype.

Docker Compose uses a named volume so the DB survives container recreation.

## Tests

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
make check
```

## Important limitations before any future live-trading work

The next major engineering step is a fully authenticated Binance User Data Stream implementation so fills, partial fills, commissions, cancellations, balance changes and execution reports arrive in real time. Binance's current Testnet documentation states that user-data events are pushed in real time and order updates arrive as `executionReport` events. REST reconciliation should still remain as a recovery path.

Other future work:

- User Data Stream / execution-report consumer.
- Proper realised P&L from fills and commissions.
- Level-2 local order book with sequence validation.
- Microprice and depth imbalance.
- Queue-position / fill probability model.
- Adverse-selection analytics.
- Prometheus metrics and Grafana dashboards.
- Historical event replay and backtesting.
- Avellaneda-Stoikov quoting model as an optional strategy.

## Operational notes

- Testnet market WebSockets are expected to disconnect after 24 hours; the client reconnects automatically.
- Binance sends WebSocket ping frames; aiohttp autoping/heartbeat is enabled.
- `bookTicker` updates when the best bid/ask changes, so Testnet can be quiet. The default stale threshold is 30 seconds rather than the overly aggressive 2.5 seconds used by the first prototype.
- API secrets belong only in `.env`, which is ignored by Git.

## Disclaimer

Trading involves risk. Testnet results do not predict live performance. Market-making can incur losses from adverse selection, fees, inventory exposure, latency and operational failures.
