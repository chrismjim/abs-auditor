#!/usr/bin/env python3
"""
ABS Auditor — main orchestrator.

Modes:
  Batch (default)  python main.py [--date YYYY-MM-DD] [--post] [--leaderboard]
  Live             python main.py --live [--date YYYY-MM-DD] [--post]

Live mode scans for newly completed games and posts a per-game thread for each
one not yet recorded in data/posted_games.json.

Batch mode (legacy) aggregates the full day into one thread — kept for manual
backfills and catch-up runs.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import traceback
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("abs_auditor")

from src.audit import audit_day, update_season_stats, load_season_stats
from src.config import ERROR_LOG, POSTED_GAMES, TIMEZONE
from src.fetch import fetch_day, fetch_game, get_abs_leaderboard, get_pitches, get_schedule
from src.post  import post_error_tweet, post_thread
from src.viz   import generate_images


# ── Posted-games state ────────────────────────────────────────────────────────

def load_posted_games() -> set[int]:
    """Return set of gamePks that have already been posted."""
    if POSTED_GAMES.exists():
        try:
            data = json.loads(POSTED_GAMES.read_text())
            return set(data.get("game_pks", []))
        except Exception as exc:
            log.warning("Could not read posted_games.json: %s", exc)
    return set()


def save_posted_games(posted: set[int]) -> None:
    POSTED_GAMES.write_text(json.dumps({"game_pks": sorted(posted)}, indent=2))


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="ABS Auditor pipeline")
    p.add_argument("--date", type=str, default=None,
                   help="Target date (YYYY-MM-DD). Defaults to yesterday (ET).")
    p.add_argument("--post", action="store_true", default=False,
                   help="Actually post to X (default: dry-run).")
    p.add_argument("--live", action="store_true", default=False,
                   help="Live mode: post per completed game (default date = today).")
    p.add_argument("--leaderboard", action="store_true", default=False,
                   help="Force leaderboard image generation.")
    return p.parse_args()


def _et_today() -> date:
    return datetime.now(ZoneInfo(TIMEZONE)).date()


def _et_yesterday() -> date:
    return _et_today() - timedelta(days=1)


# ── Live mode (per-game, real-time) ───────────────────────────────────────────

def run_live(game_date: date, dry_run: bool = True,
             force_leaderboard: bool = False) -> None:
    """
    Scan game_date for Final games not yet in posted_games.json.
    For each new completion: fetch → audit → visualise → post → record.
    """
    log.info("╔══════════════════════════════════════════════╗")
    log.info("║  ABS Auditor LIVE  |  %s  |  dry=%s  ║", game_date, dry_run)
    log.info("╚══════════════════════════════════════════════╝")

    posted    = load_posted_games()
    all_games = get_schedule(game_date)

    final_new = [
        g for g in all_games
        if g.get("status", {}).get("abstractGameState") == "Final"
        and g.get("gamePk") not in posted
    ]

    if not final_new:
        log.info("No newly completed games for %s.", game_date)
        return

    log.info("%d new completed game(s) to process.", len(final_new))

    # Fetch Statcast pitches once for the whole day (shared across all games)
    pitches_df = get_pitches(game_date)
    lb_df      = get_abs_leaderboard(game_date.year)
    is_monday  = game_date.weekday() == 0
    lb_posted  = False   # only post leaderboard once per day (first game on Mondays)

    for game in final_new:
        game_pk = game["gamePk"]
        home = game.get("teams", {}).get("home", {}).get("team", {}).get("abbreviation", "")
        away = game.get("teams", {}).get("away", {}).get("team", {}).get("abbreviation", "")
        matchup = f"{away} @ {home}"
        log.info("── %s (gamePk=%s) ──", matchup, game_pk)

        try:
            challenges, ump_accuracy = fetch_game(game_pk, game, game_date, pitches_df)

            audit_result = audit_day(challenges, pitches_df, game_date,
                                     ump_accuracy=ump_accuracy)
            audit_result["matchup"]    = matchup
            audit_result["game_pk"]    = game_pk
            audit_result["final_score"] = {
                "away": game.get("teams", {}).get("away", {}).get("score"),
                "home": game.get("teams", {}).get("home", {}).get("score"),
            }

            season_stats = update_season_stats(audit_result)

            force_lb = (is_monday and not lb_posted) or force_leaderboard
            images = generate_images(
                audit_result, season_stats, game_date,
                leaderboard_df=lb_df if force_lb else None,
                force_leaderboard=force_lb,
                game_pk=game_pk,
            )

            tweet_ids = post_thread(audit_result, images, game_date, dry_run=dry_run)
            log.info("Thread posted for %s: %s", matchup, tweet_ids)

            if not dry_run:
                posted.add(game_pk)
                save_posted_games(posted)
                if force_lb:
                    lb_posted = True

        except Exception as exc:
            tb = traceback.format_exc()
            log.error("Failed for %s (gamePk=%s):\n%s", matchup, game_pk, tb)
            ERROR_LOG.parent.mkdir(exist_ok=True)
            with ERROR_LOG.open("a") as f:
                f.write(f"\n[{datetime.now().isoformat()}] {matchup}: {exc}\n{tb}\n")
            try:
                post_error_tweet(f"{matchup}: {str(exc)[:150]}", dry_run=dry_run)
            except Exception:
                pass
            # Continue processing remaining games


# ── Batch mode (full-day aggregation, legacy / manual backfill) ───────────────

def run_batch(target_date: date, dry_run: bool = True,
              force_leaderboard: bool = False) -> None:
    log.info("╔══════════════════════════════════════════════╗")
    log.info("║  ABS Auditor BATCH |  %s  |  dry=%s  ║", target_date, dry_run)
    log.info("╚══════════════════════════════════════════════╝")

    log.info("[1/4] Fetching …")
    challenges, pitches_df = fetch_day(target_date)

    if not challenges and pitches_df.empty:
        log.info("No data for %s — likely an off-day.", target_date)
        empty_result = {
            "game_date":          target_date.isoformat(),
            "abs_challenges":     [],
            "manager_challenges": [],
            "team_stats":         {},
            "umpire_stats":       {},
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
        lb_df   = get_abs_leaderboard(target_date.year)
        images  = generate_images(empty_result, season_stats, target_date,
                                  leaderboard_df=lb_df)
        post_thread(empty_result, images, target_date, dry_run=dry_run)
        return

    log.info("[2/4] Auditing %d challenge event(s) …", len(challenges))
    audit_result = audit_day(challenges, pitches_df, target_date)
    s = audit_result["summary"]
    log.info("  ABS: %d  |  overturned: %d  |  missed: %d",
             s["total_challenges"], s["overturned"], s["missed_calls"])

    log.info("[3/4] Updating season stats …")
    season_stats = update_season_stats(audit_result)

    log.info("[4/4] Generating images …")
    lb_df  = get_abs_leaderboard(target_date.year)
    images = generate_images(audit_result, season_stats, target_date,
                             leaderboard_df=lb_df,
                             force_leaderboard=force_leaderboard)

    log.info("[5/5] Posting (dry_run=%s) …", dry_run)
    tweet_ids = post_thread(audit_result, images, target_date, dry_run=dry_run)
    log.info("Tweet IDs: %s", tweet_ids)
    log.info("Done ✓")


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    args = parse_args()

    if args.date:
        try:
            target_date = date.fromisoformat(args.date)
        except ValueError:
            log.error("Invalid date: %s  (expected YYYY-MM-DD)", args.date)
            sys.exit(1)
    else:
        target_date = _et_today() if args.live else _et_yesterday()

    dry_run = not args.post

    try:
        if args.live:
            run_live(target_date, dry_run=dry_run,
                     force_leaderboard=args.leaderboard)
        else:
            run_batch(target_date, dry_run=dry_run,
                      force_leaderboard=args.leaderboard)

    except Exception as exc:
        tb = traceback.format_exc()
        log.error("Pipeline failed:\n%s", tb)
        ERROR_LOG.parent.mkdir(exist_ok=True)
        with ERROR_LOG.open("a") as f:
            f.write(f"\n[{datetime.now().isoformat()}] {exc}\n{tb}\n")
        try:
            post_error_tweet(str(exc), dry_run=dry_run)
        except Exception:
            pass
        sys.exit(1)


if __name__ == "__main__":
    main()
