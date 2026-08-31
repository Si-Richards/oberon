from __future__ import annotations

import argparse
import bisect
import math
import os
import re
import sqlite3
import statistics
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

VERSION = "0.9.1"
DEFAULT_HORIZONS = (5, 15, 30, 60, 120, 300, 900)

TS_ALIASES = (
    "ts_ms", "timestamp_ms", "event_time_ms", "time_ms", "recv_ts_ms",
    "timestamp", "event_time", "time", "ts",
)
MID_ALIASES = ("mid", "mid_price", "mid_px", "mark_price", "price")
BID_ALIASES = ("bid", "best_bid", "bid_price", "bid_px")
ASK_ALIASES = ("ask", "best_ask", "ask_price", "ask_px")
SYMBOL_ALIASES = ("symbol", "market", "instrument", "ticker")

PREFERRED_FEATURE_TOKENS = (
    "imbalance", "obi", "microprice", "micro_price", "flow", "aggressor",
    "taker", "spread", "depth", "vol", "momentum", "return", "velocity",
    "accel", "pressure", "skew", "queue", "liquidity", "funding", "basis",
    "open_interest", "oi_", "liquidation", "btc_", "eth_",
)
EXCLUDED_TOKENS = (
    "id", "timestamp", "time_ms", "ts_ms", "sequence", "update_id", "qty",
    "quantity", "notional", "trade_id", "order_id", "sample_id", "latency",
)


@dataclass
class Source:
    path: Path
    table: str
    ts_col: str
    mid_col: str | None
    bid_col: str | None
    ask_col: str | None
    symbol_col: str | None
    numeric_cols: list[str]


@dataclass
class Row:
    ts_ms: int
    mid: float
    symbol: str
    features: dict[str, float]


def qident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _to_ms(value: object) -> int | None:
    if value is None:
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    if x < 1e11:
        x *= 1000.0
    elif x > 1e17:
        x /= 1_000_000.0
    elif x > 1e14:
        x /= 1000.0
    return int(x)


def _float(value: object) -> float | None:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _first(columns: set[str], aliases: Sequence[str]) -> str | None:
    lower = {c.lower(): c for c in columns}
    for alias in aliases:
        if alias in lower:
            return lower[alias]
    return None


def discover_databases(data_dir: Path, current_only: bool) -> list[Path]:
    dbs = sorted({*data_dir.rglob("*.db"), *data_dir.rglob("*.sqlite"), *data_dir.rglob("*.sqlite3")})
    if not current_only or not dbs:
        return dbs

    versions: dict[int, list[Path]] = defaultdict(list)
    unversioned: list[Path] = []
    for path in dbs:
        matches = re.findall(r"markets-v(\d+)", str(path).lower())
        if matches:
            versions[max(int(v) for v in matches)].append(path)
        elif not any(marker in str(path).lower() for marker in ("archive", "backup", "/old/")):
            unversioned.append(path)
    if versions:
        return sorted(versions[max(versions)])
    return sorted(unversioned or dbs)


def _numeric_columns(conn: sqlite3.Connection, table: str) -> tuple[list[str], dict[str, str]]:
    info = conn.execute(f"PRAGMA table_info({qident(table)})").fetchall()
    numeric: list[str] = []
    types: dict[str, str] = {}
    for row in info:
        name = str(row[1])
        typ = str(row[2] or "").upper()
        types[name] = typ
        if any(t in typ for t in ("INT", "REAL", "FLOA", "DOUB", "NUM", "DEC")):
            numeric.append(name)
    return numeric, types


def inspect_database(path: Path) -> list[Source]:
    out: list[Source] = []
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        return out
    try:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        for table in tables:
            numeric, types = _numeric_columns(conn, table)
            columns = set(types)
            ts = _first(columns, TS_ALIASES)
            mid = _first(columns, MID_ALIASES)
            bid = _first(columns, BID_ALIASES)
            ask = _first(columns, ASK_ALIASES)
            symbol = _first(columns, SYMBOL_ALIASES)
            if not ts or not (mid or (bid and ask)):
                continue
            out.append(Source(path, table, ts, mid, bid, ask, symbol, numeric))
    finally:
        conn.close()
    return out


def source_score(src: Source) -> int:
    score = 0
    for col in src.numeric_cols:
        c = col.lower()
        if any(tok in c for tok in PREFERRED_FEATURE_TOKENS):
            score += 5
        else:
            score += 1
    if src.symbol_col:
        score += 3
    if src.bid_col and src.ask_col:
        score += 2
    return score


def _candidate_features(src: Source) -> list[str]:
    price_cols = {c for c in (src.ts_col, src.mid_col, src.bid_col, src.ask_col) if c}
    candidates = []
    for col in src.numeric_cols:
        if col in price_cols:
            continue
        c = col.lower()
        if any(tok == c or c.endswith("_" + tok) for tok in EXCLUDED_TOKENS):
            continue
        if any(tok in c for tok in EXCLUDED_TOKENS) and not any(tok in c for tok in PREFERRED_FEATURE_TOKENS):
            continue
        candidates.append(col)
    preferred = [c for c in candidates if any(tok in c.lower() for tok in PREFERRED_FEATURE_TOKENS)]
    other = [c for c in candidates if c not in preferred]
    return preferred + other


def load_rows(src: Source, cutoff_ms: int, max_features: int = 80) -> list[Row]:
    features = _candidate_features(src)[:max_features]
    cols = [src.ts_col]
    if src.mid_col:
        cols.append(src.mid_col)
    else:
        cols.extend([src.bid_col, src.ask_col])
    if src.symbol_col:
        cols.append(src.symbol_col)
    cols.extend(features)
    select = ", ".join(qident(c) for c in cols)

    conn = sqlite3.connect(f"file:{src.path}?mode=ro", uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    rows: list[Row] = []
    try:
        query = f"SELECT {select} FROM {qident(src.table)} ORDER BY {qident(src.ts_col)}"
        for raw in conn.execute(query):
            ts = _to_ms(raw[src.ts_col])
            if ts is None or ts < cutoff_ms:
                continue
            if src.mid_col:
                mid = _float(raw[src.mid_col])
            else:
                bid = _float(raw[src.bid_col])
                ask = _float(raw[src.ask_col])
                mid = None if bid is None or ask is None else (bid + ask) / 2.0
            if mid is None or mid <= 0:
                continue
            symbol = str(raw[src.symbol_col]) if src.symbol_col and raw[src.symbol_col] is not None else src.path.stem.upper()
            f: dict[str, float] = {}
            for col in features:
                x = _float(raw[col])
                if x is not None:
                    f[col] = x
            rows.append(Row(ts, mid, symbol, f))
    finally:
        conn.close()
    return rows


def add_derived_features(rows: list[Row]) -> None:
    by_symbol: dict[str, list[Row]] = defaultdict(list)
    for r in rows:
        by_symbol[r.symbol].append(r)
    for seq in by_symbol.values():
        seq.sort(key=lambda r: r.ts_ms)
        ts = [r.ts_ms for r in seq]
        mids = [r.mid for r in seq]
        for i, r in enumerate(seq):
            for seconds in (5, 30, 60):
                j = bisect.bisect_left(ts, r.ts_ms - seconds * 1000)
                if j < i and mids[j] > 0:
                    r.features[f"derived_ret_{seconds}s_bps"] = (r.mid / mids[j] - 1.0) * 10000.0
            j0 = bisect.bisect_left(ts, r.ts_ms - 60_000)
            rets = []
            for j in range(max(j0 + 1, 1), i + 1):
                if mids[j - 1] > 0:
                    rets.append(math.log(mids[j] / mids[j - 1]) * 10000.0)
            if len(rets) >= 5:
                r.features["derived_vol_60s_bps"] = statistics.pstdev(rets)


def forward_returns(rows: list[Row], horizons: Sequence[int]) -> dict[int, list[float | None]]:
    out = {h: [None] * len(rows) for h in horizons}
    indices: dict[str, list[int]] = defaultdict(list)
    for i, r in enumerate(rows):
        indices[r.symbol].append(i)
    for ids in indices.values():
        ids.sort(key=lambda i: rows[i].ts_ms)
        ts = [rows[i].ts_ms for i in ids]
        for local_i, idx in enumerate(ids):
            r = rows[idx]
            for h in horizons:
                target = r.ts_ms + h * 1000
                j = bisect.bisect_left(ts, target, lo=local_i + 1)
                if j >= len(ids):
                    continue
                future = rows[ids[j]]
                tolerance_ms = max(5_000, int(h * 1000 * 0.25))
                if future.ts_ms - target > tolerance_ms:
                    continue
                out[h][idx] = (future.mid / r.mid - 1.0) * 10000.0
    return out


def quantile_edges(values: list[float], buckets: int = 5) -> list[float]:
    xs = sorted(values)
    if len(xs) < buckets:
        return []
    edges = []
    for i in range(1, buckets):
        pos = i * (len(xs) - 1) / buckets
        lo = int(math.floor(pos))
        hi = int(math.ceil(pos))
        if lo == hi:
            edges.append(xs[lo])
        else:
            w = pos - lo
            edges.append(xs[lo] * (1 - w) + xs[hi] * w)
    return edges


def bucket_index(value: float, edges: Sequence[float]) -> int:
    return bisect.bisect_right(edges, value)


def summarize(vals: Sequence[float]) -> dict[str, float]:
    n = len(vals)
    mean = statistics.fmean(vals)
    median = statistics.median(vals)
    stdev = statistics.stdev(vals) if n > 1 else 0.0
    se = stdev / math.sqrt(n) if n else math.inf
    return {
        "n": float(n),
        "mean": mean,
        "median": median,
        "win": sum(v > 0 for v in vals) / n * 100.0,
        "lcb95": mean - 1.96 * se,
    }


def analyze_feature(rows: list[Row], fwd: dict[int, list[float | None]], feature: str, horizons: Sequence[int], min_samples: int) -> dict | None:
    available = [(i, r.features[feature]) for i, r in enumerate(rows) if feature in r.features]
    if len(available) < min_samples * 5:
        return None
    edges = quantile_edges([v for _, v in available], 5)
    if len(set(edges)) < 2:
        return None
    split_ts = sorted(rows[i].ts_ms for i, _ in available)[int(len(available) * 0.70)]
    result = {"feature": feature, "edges": edges, "horizons": {}, "train_test": {}}
    best_score = -math.inf
    for h in horizons:
        buckets: list[list[float]] = [[] for _ in range(5)]
        train_low: list[float] = []
        train_high: list[float] = []
        test_low: list[float] = []
        test_high: list[float] = []
        for i, value in available:
            ret = fwd[h][i]
            if ret is None:
                continue
            b = bucket_index(value, edges)
            buckets[b].append(ret)
            if b == 0:
                (train_low if rows[i].ts_ms <= split_ts else test_low).append(ret)
            elif b == 4:
                (train_high if rows[i].ts_ms <= split_ts else test_high).append(ret)
        if min(len(buckets[0]), len(buckets[4])) < min_samples:
            continue
        bs = [summarize(v) if v else None for v in buckets]
        low, high = bs[0], bs[4]
        assert low and high
        spread = high["mean"] - low["mean"]
        train_spread = statistics.fmean(train_high) - statistics.fmean(train_low) if train_high and train_low else math.nan
        test_spread = statistics.fmean(test_high) - statistics.fmean(test_low) if test_high and test_low else math.nan
        direction_ok = math.isfinite(train_spread) and math.isfinite(test_spread) and train_spread * test_spread > 0
        score = abs(test_spread) * (1.0 if direction_ok else 0.20) if math.isfinite(test_spread) else -math.inf
        best_score = max(best_score, score)
        result["horizons"][h] = {"buckets": bs, "spread": spread}
        result["train_test"][h] = {
            "train_spread": train_spread,
            "test_spread": test_spread,
            "direction_ok": direction_ok,
            "score": score,
        }
    if not result["horizons"]:
        return None
    result["score"] = best_score
    return result


def print_report(rows: list[Row], analyses: list[dict], horizons: Sequence[int], sources: list[Source], elapsed: float, top: int) -> None:
    symbols = sorted({r.symbol for r in rows})
    print(f"Oberon v{VERSION} signal discovery report")
    print("=" * 78)
    print(f"samples={len(rows):,} symbols={len(symbols)} sources={len(sources)} elapsed={elapsed:.1f}s")
    print(f"horizons={','.join(str(h) for h in horizons)}s research_only=True chronological_split=70/30")
    print("\nTop out-of-sample signal candidates")
    print("-" * 78)
    shown = 0
    for a in sorted(analyses, key=lambda x: x["score"], reverse=True):
        if shown >= top:
            break
        best_h = max(a["train_test"], key=lambda h: a["train_test"][h]["score"])
        tt = a["train_test"][best_h]
        hdata = a["horizons"][best_h]
        low = hdata["buckets"][0]
        high = hdata["buckets"][4]
        if not low or not high:
            continue
        print(
            f"{a['feature'][:34]:34s} h={best_h:>4}s "
            f"test_spread={tt['test_spread']:+7.2f}bps "
            f"train={tt['train_spread']:+7.2f} "
            f"consistent={'yes' if tt['direction_ok'] else 'NO ':3s} "
            f"n={int(low['n']) + int(high['n']):>6d}"
        )
        shown += 1

    print("\nSignal decay / bucket detail")
    print("-" * 78)
    for a in sorted(analyses, key=lambda x: x["score"], reverse=True)[: min(top, 12)]:
        print(f"\n{a['feature']}")
        print(" horizon   lowQ mean   highQ mean   spread    test spread  consistent")
        for h in horizons:
            if h not in a["horizons"]:
                continue
            d = a["horizons"][h]
            tt = a["train_test"][h]
            lo = d["buckets"][0]
            hi = d["buckets"][4]
            if lo and hi:
                print(
                    f" {h:>5}s   {lo['mean']:+9.2f}  {hi['mean']:+10.2f}  {d['spread']:+8.2f}  "
                    f"{tt['test_spread']:+11.2f}  {'yes' if tt['direction_ok'] else 'no'}"
                )

    print("\nInterpretation guardrails")
    print("-" * 78)
    print("* This report discovers associations; it does not enable trading or quote skew.")
    print("* Prefer signals whose train/test spread keeps the same sign across several horizons.")
    print("* Re-run on later non-overlapping windows before promoting any signal to execution logic.")
    print("* A small directional edge can still be useful as an adverse-selection gate even when")
    print("  it is smaller than the full round-trip fee hurdle.")


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Oberon schema-adaptive signal discovery report")
    p.add_argument("--hours", type=float, default=168.0)
    p.add_argument("--horizons", default=",".join(map(str, DEFAULT_HORIZONS)))
    p.add_argument("--data-dir", default=os.getenv("OBERON_DATA_DIR", "/data"))
    p.add_argument("--current-only", action="store_true")
    p.add_argument("--min-samples", type=int, default=100)
    p.add_argument("--top", type=int, default=30)
    args = p.parse_args(argv)

    horizons = tuple(sorted({int(x.strip()) for x in args.horizons.split(",") if x.strip()}))
    if not horizons or any(h <= 0 for h in horizons):
        p.error("--horizons must contain positive integer seconds")
    started = time.monotonic()
    cutoff_ms = int(time.time() * 1000 - args.hours * 3600 * 1000)

    dbs = discover_databases(Path(args.data_dir), args.current_only)
    print(f"[signal] stage=discover databases={len(dbs)} elapsed={time.monotonic()-started:.1f}s", flush=True)
    all_sources = [s for db in dbs for s in inspect_database(db)]
    if not all_sources:
        raise SystemExit("No compatible SQLite table found (need timestamp + mid, or timestamp + bid/ask).")

    chosen_by_db: dict[Path, Source] = {}
    for s in all_sources:
        if s.path not in chosen_by_db or source_score(s) > source_score(chosen_by_db[s.path]):
            chosen_by_db[s.path] = s
    sources = list(chosen_by_db.values())

    rows: list[Row] = []
    for n, src in enumerate(sources, 1):
        loaded = load_rows(src, cutoff_ms)
        rows.extend(loaded)
        if n == 1 or n % 5 == 0 or n == len(sources):
            print(f"[signal] sources={n}/{len(sources)} samples={len(rows)} elapsed={time.monotonic()-started:.1f}s", flush=True)
    if len(rows) < args.min_samples * 5:
        raise SystemExit(f"Only {len(rows)} usable samples; need at least {args.min_samples * 5}.")

    rows.sort(key=lambda r: (r.symbol, r.ts_ms))
    print(f"[signal] stage=derived_features samples={len(rows)} elapsed={time.monotonic()-started:.1f}s", flush=True)
    add_derived_features(rows)
    fwd = forward_returns(rows, horizons)

    feature_counts: dict[str, int] = defaultdict(int)
    for r in rows:
        for feature in r.features:
            feature_counts[feature] += 1
    candidates = [f for f, n in feature_counts.items() if n >= args.min_samples * 5]
    print(f"[signal] stage=analyze features={len(candidates)} elapsed={time.monotonic()-started:.1f}s", flush=True)
    analyses = []
    for feature in candidates:
        a = analyze_feature(rows, fwd, feature, horizons, args.min_samples)
        if a:
            analyses.append(a)

    print_report(rows, analyses, horizons, sources, time.monotonic() - started, args.top)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
