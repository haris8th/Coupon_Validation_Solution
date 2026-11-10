"""CLI: python -m platform_detector.cli domains.csv -o results.csv"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections import Counter
from pathlib import Path

from .detector import Detector, Settings
from .io_utils import read_urls_from_csv, results_to_csv


async def _run(args: argparse.Namespace) -> int:
    if args.url:
        urls = args.url
    else:
        urls = read_urls_from_csv(Path(args.input).read_text(encoding="utf-8-sig", errors="replace"))
    if not urls:
        print("no URLs found", file=sys.stderr)
        return 2
    s = Settings()
    s.concurrency = args.concurrency
    s.timeout = args.timeout
    s.use_browser = args.browser
    s.headless = args.headless
    s.dns = not args.no_dns
    t0 = time.monotonic()
    done = 0

    async with Detector(s) as det:
        async def one(u: str):
            nonlocal done
            r = await det.detect(u)
            done += 1
            if not args.quiet:
                note = f"  ({r.reason})" if r.reason else ""
                print(f"[{done}/{len(urls)}] {r.platform:<26} {r.confidence:<5} {u}{note}", file=sys.stderr)
            return r

        results = await asyncio.gather(*(one(u) for u in urls))

    rows = [r.to_dict() for r in results]
    if args.output:
        Path(args.output).write_text(results_to_csv(rows), encoding="utf-8", newline="")
    elif args.json:
        print(json.dumps(rows, indent=2))
    else:
        sys.stdout.write(results_to_csv(rows))
    counts = Counter(r["platform"] for r in rows)
    summary = ", ".join(f"{k}={v}" for k, v in counts.most_common())
    print(f"\n{len(rows)} sites in {time.monotonic() - t0:.1f}s: {summary}", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Detect the e-commerce platform for a CSV of domains.")
    p.add_argument("input", nargs="?", help="CSV with a url/domain column (or one domain per line)")
    p.add_argument("-u", "--url", action="append", help="check a single URL (repeatable) instead of a CSV")
    p.add_argument("-o", "--output", help="write results CSV here (default: stdout)")
    p.add_argument("--json", action="store_true", help="print JSON instead of CSV when no -o")
    p.add_argument("-c", "--concurrency", type=int, default=20)
    p.add_argument("-t", "--timeout", type=float, default=10.0, help="per-request timeout seconds")
    p.add_argument("--browser", action="store_true", help="enable Playwright fallback for bot-walled sites")
    p.add_argument("--headless", action="store_true", help="hide the fallback browser window (default: visible)")
    p.add_argument("--no-dns", action="store_true", help="skip the DNS stage")
    p.add_argument("-q", "--quiet", action="store_true")
    args = p.parse_args(argv)
    if not args.input and not args.url:
        p.error("give a CSV path or --url")
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
