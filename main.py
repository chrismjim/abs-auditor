#!/usr/bin/env python3
"""
ABS Auditor — main orchestrator.

Usage:
  python main.py                          # yesterday, dry-run ON
  python main.py --date 2025-04-10        # specific date, dry-run ON
  python main.py --date 2025-04-10 --post # actually post to X
"""
from __future__ import annotations

import argparse
import logging
import sys
import traceback
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

# Configure logging before any other imports
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("abs_auditor")

from src.audit import audit_day, update_season_stats, load_season_stats
from src.config import ERROR_LOG, TIMEZONE
from src.fetch import fetch_day, get_abs_leaderboard
from src.post  import post_error_tweet, post_thread
from src.viz   import generate_images


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="ABS Auditor pipeline")
    p.add_argument(
        "--date",
        type=str,
        default=None,
        help="Target date (YYYY-MM-DD). Defaults to yesterday (ET).",
    )
    p.add_argument(
        "--post",
        action="store_true",
        default=False,
        help="Actually post to X. Omit to run in dry-run mode (default).",
    )
    p.add_argument(
        "--leaderboard",
        action="store_true",
        default=False,
        help="Force generation of the season leaderboard image (normally Mondays only).",
    )
    return p.parse_args()


def yesterday_et() -> date:
    tz = ZoneInfo(TIMEZONE)
    now = datetime.now(tz)
    return (now - timedelta(days=1)).date()


def run(target_date: date, dry_run: bool = True,
        force_leaderboard: bool = False) -> None:
    log.info("╔══════════════════════════════════════════════╗")
    log.info("║  ABS Auditor  |  %s  |  dry_run=%s  ║", target_date, dry_run)
    log.info("╚══════════════════════════════════════════════╝")

    # 1. Fetch
    log.info("[1/4] Fetching data …")
    challenges, pitches_df = fetch_day(target_date)

    if not challenges and pitches_df.empty:
        log.info("No data for %s — likely an off-day. Exiting.", target_date)
        # Still post a no-challenges tweet if --post
        empty_result = {
            "game_date":          target_date.isoformat(),
            "abs_challenges":     [],
            "manager_challenges": [],
            "team_stats":         {},
            "umpire_stats":       {},
            "focus_abs":          [],
            "focus_mgr":          [],
            "storylines":         [],
            "summary": {
                "total_challenges": 0,
                "overturned":       0,
                "missed_calls":     0,
                "correct_upheld":   0,
                "no_challenges":    True,
            },
        }
        season_stats = load_season_stats()
        lb_df = get_abs_leaderboard(target_date.year)
        images = generate_images(empty_result, season_stats, target_date,
                                 leaderboard_df=lb_df)
        post_thread(empty_result, images, target_date, dry_run=dry_run)
        return

    # 2. Audit
    log.info("[2/4] Auditing %d challenge event(s) …", len(challenges))
    audit_result = audit_day(challenges, pitches_df, target_date)
    summary = audit_result["summary"]
    log.info(
        "  ABS challenges: %d  |  overturned: %d  |  missed: %d",
        summary["total_challenges"],
        summary["overturned"],
        summary["missed_calls"],
    )

    # 3. Update season stats
    log.info("[3/4] Updating season stats …")
    season_stats = update_season_stats(audit_result)

    # 4. Visualise
    log.info("[4/4] Generating images …")
    lb_df = get_abs_leaderboard(target_date.year)
    images = generate_images(audit_result, season_stats, target_date,
                             leaderboard_df=lb_df,
                             force_leaderboard=force_leaderboard)
    for name, path in images.items():
        if path:
            log.info("  %s → %s", name, path)

    # 5. Post
    log.info("[5/5] Posting to X (dry_run=%s) …", dry_run)
    tweet_ids = post_thread(audit_result, images, target_date, dry_run=dry_run)
    log.info("Tweet IDs: %s", tweet_ids)

    log.info("Done ✓")


def main() -> None:
    args = parse_args()

    if args.date:
        try:
            target_date = date.fromisoformat(args.date)
        except ValueError:
            log.error("Invalid date format: %s  (expected YYYY-MM-DD)", args.date)
            sys.exit(1)
    else:
        target_date = yesterday_et()

    dry_run = not args.post

    try:
        run(target_date, dry_run=dry_run, force_leaderboard=args.leaderboard)
    except Exception as exc:
        tb = traceback.format_exc()
        log.error("Pipeline failed:\n%s", tb)

        # Write to error log
        ERROR_LOG.parent.mkdir(exist_ok=True)
        with ERROR_LOG.open("a") as f:
            f.write(f"\n[{datetime.now().isoformat()}] {exc}\n{tb}\n")

        # Attempt error tweet
        try:
            post_error_tweet(str(exc), dry_run=dry_run)
        except Exception:
            pass   # don't let this mask the original error

        sys.exit(1)


if __name__ == "__main__":
    main()
