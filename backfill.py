#!/usr/bin/env python3
"""
ABS Auditor — historical backfill.

Rebuilds (or extends) data/season_stats.json by running the full audit
pipeline for every date in a range without posting to X.

Usage:
  python backfill.py --start 2025-04-01 --end 2025-04-10
  python backfill.py --start 2025-04-01              # end defaults to yesterday
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import date, datetime, timedelta

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("backfill")

from src.audit import audit_day, update_season_stats
from src.config import SEASON_STATS
from src.fetch import fetch_day


def date_range(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="ABS Auditor backfill")
    p.add_argument("--start", required=True,
                   help="Start date YYYY-MM-DD (inclusive)")
    p.add_argument("--end",   default=None,
                   help="End date YYYY-MM-DD (inclusive). Defaults to yesterday.")
    p.add_argument("--delay", type=float, default=2.0,
                   help="Seconds between requests to avoid rate-limiting (default 2)")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    try:
        start = date.fromisoformat(args.start)
    except ValueError:
        log.error("Invalid start date: %s", args.start)
        sys.exit(1)

    if args.end:
        try:
            end = date.fromisoformat(args.end)
        except ValueError:
            log.error("Invalid end date: %s", args.end)
            sys.exit(1)
    else:
        end = date.today() - timedelta(days=1)

    if start > end:
        log.error("start (%s) is after end (%s)", start, end)
        sys.exit(1)

    log.info("Backfill: %s → %s", start, end)
    total_days = (end - start).days + 1
    ok = 0
    skipped = 0

    for i, d in enumerate(date_range(start, end), 1):
        log.info("── [%d/%d] %s ──", i, total_days, d)
        try:
            challenges, pitches_df = fetch_day(d)
            if not challenges:
                log.info("  No challenges / off-day — skipping stats update")
                skipped += 1
            else:
                audit_result = audit_day(challenges, pitches_df, d)
                update_season_stats(audit_result)
                s = audit_result["summary"]
                log.info(
                    "  ✓ %d challenges, %d overturned, %d missed",
                    s["total_challenges"], s["overturned"], s["missed_calls"]
                )
                ok += 1
        except Exception as exc:
            log.warning("  Error on %s: %s", d, exc)

        if i < total_days:
            time.sleep(args.delay)

    log.info("Backfill complete: %d days processed, %d skipped", ok, skipped)
    if SEASON_STATS.exists():
        log.info("Season stats written to %s", SEASON_STATS)


if __name__ == "__main__":
    main()
