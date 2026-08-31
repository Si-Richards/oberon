# Oberon v0.9.1

Oberon is a Binance USD-M Futures **market microstructure research and paper market-making** project. v0.9.1 focuses on signal discovery: collecting high-frequency public Futures market data, storing one SQLite database per symbol, and testing whether observable market states predict later price movement or adverse selection.

> v0.9.1 intentionally does **not** submit live Binance orders. The collector uses public market-data WebSockets only. Optional paper fills are local simulations.

## What v0.9.1 adds

- Binance Futures partial-depth (`depth20@100ms`), aggregate-trade and mark-price streams.
- Per-symbol SQLite market databases under `/data/markets-v091`.
- L1/L5/L10/L20 order-book imbalance.
- Depth notional at 5/10/20 levels.
- Microprice and microprice displacement in bps.
- Aggressor trade-flow imbalance over 5/30/60 seconds.
- 5/30/60 second backward returns and 60-second realised volatility.
- Mark price, index price and funding rate snapshots from the mark-price stream.
- `directional_report` for directional cohort discovery.
- `signal_report` with 5/15/30/60/120/300/900 second forward returns, quintile analysis, signal decay and a chronological 70/30 train/test split.
- Optional local paper quotes/fills. No exchange order submission.

## Quick start

```bash
cp .env.example .env
nano .env
docker compose up -d --build
docker logs -f binance-market-maker
```

The default container name remains `binance-market-maker` so the reporting commands match earlier Oberon deployments.

## Signal discovery

After collecting data:

```bash
docker exec binance-market-maker \
  python -m app.signal_report \
  --hours 72 \
  --horizons 5,15,30,60,120,300,900 \
  --min-samples 100 \
  --top 30 \
  --current-only
```

For a seven-day confirmation window:

```bash
docker exec binance-market-maker \
  python -m app.signal_report \
  --hours 168 \
  --horizons 5,15,30,60,120,300,900 \
  --min-samples 250 \
  --top 50 \
  --current-only
```

## Directional report

```bash
docker exec binance-market-maker \
  python -m app.directional_report \
  --hours 72 \
  --top 50 \
  --current-only
```

By default it evaluates a 300-second horizon and applies a 16.5 bps expected round-trip hurdle. Override with `--horizon` and `--round-trip-bps`.

## Database sizes

```bash
docker exec binance-market-maker python -m app.db_report --data-dir /data
```

## Data schema

Each symbol database contains `market_samples` with timestamps, bid/ask/mid, spread, depth, OBI, microprice, flow, return, volatility, mark/index price and funding rate. `paper_fills` is used only when `PAPER_ENABLED=true`.

## Research interpretation

A discovered relationship is not promoted to execution merely because its in-sample mean is positive. The signal report splits observations chronologically 70/30 and heavily penalises relationships that reverse sign out of sample. Re-run promising signals on later non-overlapping windows before using them as quote-skew or risk-gating inputs.

The most useful first production use of a validated signal is expected to be **adverse-selection avoidance and quote skew**, not outright directional speculation.

## Tests

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
make check
```

## Safety

- Research/paper only.
- Public Binance Futures feeds only.
- No API key or secret is required.
- No authenticated order endpoint exists in this release.
- `RESEARCH_ONLY=true` is required when paper mode is enabled.

## Version

`0.9.1` — signal discovery research release.
