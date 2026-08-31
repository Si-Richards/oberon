from __future__ import annotations

import argparse
import bisect
import math
import os
import statistics
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .signal_report import discover_databases, inspect_database, load_rows, source_score

VERSION = "0.9.1"


@dataclass
class PathResult:
    symbol: str
    side: str
    feature: str
    bucket: str
    n: int
    mean_bps: float
    median_bps: float
    win_pct: float
    lcb95_bps: float
    gross_after_move_bps: float
    net_after_cost_bps: float


def _summary(values: list[float]) -> tuple[float, float, float, float]:
    mean = statistics.fmean(values)
    median = statistics.median(values)
    win = sum(v > 0 for v in values) / len(values) * 100.0
    sd = statistics.stdev(values) if len(values) > 1 else 0.0
    lcb = mean - 1.96 * sd / math.sqrt(len(values))
    return mean, median, win, lcb


def analyze(rows, horizon: int, min_samples: int, round_trip_bps: float) -> list[PathResult]:
    by_symbol: dict[str, list] = {}
    for r in rows:
        by_symbol.setdefault(r.symbol, []).append(r)
    out: list[PathResult] = []
    feature_names = (
        "obi_l20", "obi_l10", "trade_flow_30s", "trade_flow_60s",
        "microprice_bps", "ret_30s_bps", "ret_60s_bps",
    )
    for symbol, seq in by_symbol.items():
        seq.sort(key=lambda r: r.ts_ms)
        ts = [r.ts_ms for r in seq]
        for feature in feature_names:
            vals = [r.features.get(feature) for r in seq if feature in r.features]
            if len(vals) < min_samples * 4:
                continue
            sorted_vals = sorted(float(v) for v in vals)
            q20 = sorted_vals[int(0.20 * (len(sorted_vals) - 1))]
            q80 = sorted_vals[int(0.80 * (len(sorted_vals) - 1))]
            cohorts = {"LOW": [], "HIGH": []}
            for i, r in enumerate(seq):
                v = r.features.get(feature)
                if v is None:
                    continue
                target = r.ts_ms + horizon * 1000
                j = bisect.bisect_left(ts, target, i + 1)
                if j >= len(seq) or seq[j].ts_ms - target > max(5000, horizon * 250):
                    continue
                ret = (seq[j].mid / r.mid - 1.0) * 10000.0
                if v <= q20:
                    cohorts["LOW"].append(ret)
                elif v >= q80:
                    cohorts["HIGH"].append(ret)
            for bucket, rets in cohorts.items():
                if len(rets) < min_samples:
                    continue
                side = "BUY" if statistics.fmean(rets) >= 0 else "SELL"
                directional = rets if side == "BUY" else [-x for x in rets]
                mean, median, win, lcb = _summary(directional)
                out.append(PathResult(
                    symbol, side, feature, bucket, len(rets), mean, median, win, lcb, mean, mean - round_trip_bps
                ))
    return out


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Oberon paired directional Futures report")
    p.add_argument("--hours", type=float, default=72.0)
    p.add_argument("--top", type=int, default=50)
    p.add_argument("--horizon", type=int, default=300)
    p.add_argument("--data-dir", default=os.getenv("OBERON_DATA_DIR", "/data"))
    p.add_argument("--current-only", action="store_true")
    p.add_argument("--min-samples", type=int, default=50)
    p.add_argument("--round-trip-bps", type=float, default=float(os.getenv("EXPECTED_ROUND_TRIP_BPS", "16.5")))
    args = p.parse_args(argv)
    started = time.monotonic()
    cutoff = int(time.time() * 1000 - args.hours * 3_600_000)
    dbs = discover_databases(Path(args.data_dir), args.current_only)
    print(f"[directional] stage=load databases={len(dbs)} elapsed={time.monotonic()-started:.1f}s", flush=True)
    sources = []
    for db in dbs:
        candidates = inspect_database(db)
        if candidates:
            sources.append(max(candidates, key=source_score))
    rows = []
    for i, src in enumerate(sources, 1):
        rows.extend(load_rows(src, cutoff))
        if i == 1 or i % 5 == 0 or i == len(sources):
            print(f"[directional] databases={i}/{len(sources)} samples={len(rows)} elapsed={time.monotonic()-started:.1f}s", flush=True)
    print(f"[directional] stage=paired_paths samples={len(rows)} elapsed={time.monotonic()-started:.1f}s", flush=True)
    results = analyze(rows, args.horizon, args.min_samples, args.round_trip_bps)
    print(f"[directional] stage=summarize paths={len(results)} elapsed={time.monotonic()-started:.1f}s", flush=True)
    print(f"[directional] complete elapsed={time.monotonic()-started:.1f}s")
    print(f"Oberon v{VERSION} paired directional Futures report")
    print("=" * 104)
    print(f"window={args.hours:g}h horizon={args.horizon}s samples={len(rows):,} paths={len(results):,} expected_round_trip={args.round_trip_bps:.2f}bps research_only=True")
    print("\nTop directional cohorts")
    print("-" * 104)
    print("symbol          side feature                bucket      n    gross   net/cost    LCB95   win%")
    for r in sorted(results, key=lambda x: (x.lcb95_bps, x.net_after_cost_bps), reverse=True)[:args.top]:
        print(f"{r.symbol[:14]:14s} {r.side:4s} {r.feature[:22]:22s} {r.bucket:5s} {r.n:7d} {r.mean_bps:+8.2f} {r.net_after_cost_bps:+9.2f} {r.lcb95_bps:+8.2f} {r.win_pct:6.1f}")
    if not results:
        print("No cohorts met the minimum sample requirement.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
