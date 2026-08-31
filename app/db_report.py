from __future__ import annotations

import argparse
from pathlib import Path


def main() -> int:
    p = argparse.ArgumentParser(description="List Oberon market databases by size")
    p.add_argument("--data-dir", default="/data")
    args = p.parse_args()
    files = sorted(Path(args.data_dir).rglob("*.db"), key=lambda p: p.stat().st_size, reverse=True)
    total = sum(p.stat().st_size for p in files)
    print(f"databases={len(files)} total={total/1024/1024:.1f} MiB")
    for path in files:
        print(f"{path.stat().st_size/1024/1024:9.1f} MiB  {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
