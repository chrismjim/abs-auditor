"""
ABS Auditor — challenge processing and scoring.

Takes raw challenge events from fetch.py and:
  1. Cross-references pitch location from Statcast.
  2. Scores each challenge outcome.
  3. Computes team- and umpire-level summaries.
  4. Updates the persistent season_stats.json.
"""
from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from src.config import (
    FOCUS_TEAM,
    SEASON_STATS,
    ZONE_HALF_WIDTH_FT,
)
from src.fetch import enrich_challenge_with_statcast

log = logging.getLogger(__name__)

# ── Outcome labels ────────────────────────────────────────────────────────────
# Used downstream by viz.py and post.py

CORRECT_OVERTURN   = "correct_overturn"    # ABS/challenger was right, call flipped
INCORRECT_OVERTURN = "incorrect_overturn"  # call flipped but original was correct
CORRECT_UPHELD     = "correct_upheld"      # original call was right, challenge denied
MISSED_CALL        = "missed_call"         # original call was wrong, challenge denied


# ── Strike zone helpers ───────────────────────────────────────────────────────

def pitch_in_zone(pitch_x: float | None, pitch_z: float | None,
                  sz_top: float | None, sz_bot: float | None) -> bool | None:
    """
    Return True if pitch coords are inside the strike zone, False if outside,
    None if we don't have enough data to decide.

    Coordinates are in feet from centre of plate.
    """
    if pitch_x is None or pitch_z is None:
        return None
    if sz_top is None or sz_bot is None:
        return None
    in_width  = abs(pitch_x) <= ZONE_HALF_WIDTH_FT
    in_height = sz_bot <= pitch_z <= sz_top
    return in_width and in_height


def edge_distance(pitch_x: float | None, pitch_z: float | None,
                  sz_top: float | None, sz_bot: float | None) -> float | None:
    """
    Signed distance from nearest zone edge (negative = outside, positive = inside).
    Returns None if coords are unavailable.
    """
    if pitch_x is None or pitch_z is None or sz_top is None or sz_bot is None:
        return None
    dx = ZONE_HALF_WIDTH_FT - abs(pitch_x)
    dz_top = sz_top - pitch_z
    dz_bot = pitch_z - sz_bot
    dz = min(dz_top, dz_bot)
    return min(dx, dz)   # positive = inside, negative = outside


# ── Pitch location enrichment ─────────────────────────────────────────────────



# ── Scoring ───────────────────────────────────────────────────────────────────

def score_abs_challenge(challenge: dict) -> dict:
    """
    Score an ABS challenge and add 'outcome' + 'in_zone' + 'edge_dist' fields.
    """
    assert challenge["challenge_type"] == "absChallenge"

    overturned = challenge.get("overturned")       # True/False/None
    px  = challenge.get("pitch_x")
    pz  = challenge.get("pitch_z")
    top = challenge.get("sz_top")
    bot = challenge.get("sz_bot")

    in_zone  = pitch_in_zone(px, pz, top, bot)
    edge_d   = edge_distance(px, pz, top, bot)
    orig     = (challenge.get("original_call") or "").lower()

    challenge["in_zone"]   = in_zone
    challenge["edge_dist"] = edge_d

    if overturned is None:
        challenge["outcome"] = None
        return challenge

    # Determine if the original call was correct
    # "called_strike" → original said strike (pitch should be in zone to be correct)
    # "ball"          → original said ball   (pitch should be outside zone to be correct)
    if in_zone is None:
        # We can't verify — record overturned/upheld without a correctness label
        challenge["outcome"] = CORRECT_OVERTURN if overturned else CORRECT_UPHELD
        challenge["outcome_uncertain"] = True
        return challenge

    original_call_was_strike = "strike" in orig
    original_call_was_ball   = "ball" in orig

    # If we can't tell from the description, infer from overturn + zone
    if not original_call_was_strike and not original_call_was_ball:
        # Heuristic: if pitch is in zone, the "correct" call is strike
        original_call_was_strike = not in_zone   # call was wrong → strike in zone
        original_call_was_ball   = in_zone

    original_correct = (original_call_was_strike and in_zone) or \
                       (original_call_was_ball and not in_zone)

    if overturned and not original_correct:
        challenge["outcome"] = CORRECT_OVERTURN
    elif overturned and original_correct:
        challenge["outcome"] = INCORRECT_OVERTURN
    elif not overturned and original_correct:
        challenge["outcome"] = CORRECT_UPHELD
    else:
        challenge["outcome"] = MISSED_CALL

    challenge["outcome_uncertain"] = False
    return challenge


def score_manager_challenge(challenge: dict) -> dict:
    """Score a manager replay challenge (non-ABS)."""
    # Accept both managerChallenge and umpireReview types
    assert challenge["challenge_type"] in ("managerChallenge", "umpireReview")

    overturned = challenge.get("overturned")
    subtype    = (challenge.get("challenge_subtype") or "").lower()
    desc       = (challenge.get("description") or "").lower()

    # Flag borderline plays based on the challenge subtype
    borderline_subtypes = {"tag play", "force play", "play at 1st", "timing play",
                           "slide interference", "home-plate collision"}
    challenge["borderline"] = subtype in borderline_subtypes

    if overturned is True:
        challenge["outcome"] = CORRECT_OVERTURN
    elif overturned is False:
        challenge["outcome"] = CORRECT_UPHELD
    else:
        challenge["outcome"] = None

    return challenge


# ── Main audit function ───────────────────────────────────────────────────────

def audit_day(raw_challenges: list[dict], pitches_df: pd.DataFrame,
              game_date: date) -> dict:
    """
    Process all challenge events for a day.

    Returns a structured audit result dict consumed by viz.py and post.py.
    """
    abs_challenges:     list[dict] = []
    manager_challenges: list[dict] = []

    for ch in raw_challenges:
        ch = enrich_challenge_with_statcast(ch, pitches_df)

        if ch["challenge_type"] == "absChallenge":
            ch = score_abs_challenge(ch)
            abs_challenges.append(ch)
        elif ch["challenge_type"] in ("managerChallenge", "umpireReview"):
            ch = score_manager_challenge(ch)
            manager_challenges.append(ch)
        else:
            log.debug("Unknown challenge type: %s", ch["challenge_type"])

    # ── Team summary ──────────────────────────────────────────────────────────
    team_stats: dict[str, dict] = {}
    all_scored = abs_challenges + manager_challenges
    for ch in all_scored:
        for team_key in ("home_team", "away_team"):
            team = ch.get(team_key)
            if not team:
                continue

            # Only count challenges where one of the teams was challenging
            # (we don't know which team challenged from the API in all cases,
            # so we attribute to both teams in the game — good enough for leaderboard)
            stats = team_stats.setdefault(team, {
                "challenges": 0, "overturned": 0, "missed_calls": 0
            })

        outcome = ch.get("outcome")
        home = ch.get("home_team")
        away = ch.get("away_team")
        for t in [home, away]:
            if not t:
                continue
            team_stats.setdefault(t, {"challenges": 0, "overturned": 0, "missed_calls": 0})
            if ch["challenge_type"] == "absChallenge":
                team_stats[t]["challenges"] += 1
                if outcome == CORRECT_OVERTURN:
                    team_stats[t]["overturned"] += 1
                elif outcome == MISSED_CALL:
                    team_stats[t]["missed_calls"] += 1

    # ── Umpire summary ────────────────────────────────────────────────────────
    umpire_stats: dict[str, dict] = {}
    for ch in abs_challenges:
        umpire = ch.get("umpire")
        if not umpire:
            continue
        u = umpire_stats.setdefault(umpire, {"total": 0, "correct": 0})
        u["total"] += 1
        if ch.get("outcome") in (CORRECT_UPHELD, CORRECT_OVERTURN):
            u["correct"] += 1

    for u in umpire_stats.values():
        u["correct_rate"] = u["correct"] / u["total"] if u["total"] else 0.0

    # ── Focus team challenges ─────────────────────────────────────────────────
    focus_abs = [
        c for c in abs_challenges
        if c.get("home_team") == FOCUS_TEAM or c.get("away_team") == FOCUS_TEAM
    ]
    focus_mgr = [
        c for c in manager_challenges
        if c.get("home_team") == FOCUS_TEAM or c.get("away_team") == FOCUS_TEAM
    ]

    # ── Storyline generation ──────────────────────────────────────────────────
    storylines = _generate_storylines(abs_challenges, umpire_stats, game_date)

    result = {
        "game_date":           game_date.isoformat(),
        "abs_challenges":      abs_challenges,
        "manager_challenges":  manager_challenges,
        "team_stats":          team_stats,
        "umpire_stats":        umpire_stats,
        "focus_abs":           focus_abs,
        "focus_mgr":           focus_mgr,
        "storylines":          storylines,
        "summary": {
            "total_challenges": len(abs_challenges),
            "overturned":       sum(1 for c in abs_challenges if c.get("outcome") == CORRECT_OVERTURN),
            "missed_calls":     sum(1 for c in abs_challenges if c.get("outcome") == MISSED_CALL),
            "correct_upheld":   sum(1 for c in abs_challenges if c.get("outcome") == CORRECT_UPHELD),
            "no_challenges":    len(abs_challenges) == 0,
        },
    }
    return result


def _generate_storylines(abs_challenges: list[dict], umpire_stats: dict,
                          game_date: date) -> list[str]:
    """Build 1-3 short storyline strings for the thread reply."""
    stories: list[str] = []

    # Best/worst umpire crew
    if umpire_stats:
        sorted_umps = sorted(umpire_stats.items(),
                             key=lambda x: x[1]["correct_rate"], reverse=True)
        best_ump, best_stats = sorted_umps[0]
        rate = best_stats["correct_rate"] * 100
        if best_stats["total"] >= 2:
            stories.append(
                f"Umpire {best_ump} had the best accuracy rate ({rate:.0f}%)."
            )

    # Most notable missed call (closest pitch to zone that was wrongly upheld)
    missed = [c for c in abs_challenges if c.get("outcome") == MISSED_CALL
              and c.get("edge_dist") is not None]
    if missed:
        worst = max(missed, key=lambda c: abs(c["edge_dist"]))
        dist_in = abs(worst["edge_dist"]) * 12  # ft → inches
        inn = worst.get("inning", "?")
        stories.append(
            f"Biggest missed call: {worst['pitcher']} vs {worst['batter']} "
            f"(inning {inn}) — pitch was {dist_in:.1f}\" off the corner."
        )

    # Focus team performance
    focus = [c for c in abs_challenges
             if c.get("home_team") == FOCUS_TEAM or c.get("away_team") == FOCUS_TEAM]
    if focus:
        won = sum(1 for c in focus if c.get("outcome") == CORRECT_OVERTURN)
        stories.append(
            f"{FOCUS_TEAM} challenged {len(focus)} time(s), went {won}-for-{len(focus)}."
        )

    return stories


# ── Season stats persistence ──────────────────────────────────────────────────

def load_season_stats() -> dict:
    if SEASON_STATS.exists():
        try:
            return json.loads(SEASON_STATS.read_text())
        except Exception as exc:
            log.warning("Could not read season stats: %s", exc)
    return {
        "last_updated":    None,
        "total_challenges": 0,
        "total_overturned": 0,
        "team_stats":       {},
        "umpire_stats":     {},
    }


def update_season_stats(audit_result: dict) -> dict:
    """Merge today's audit into the running season totals and persist."""
    stats = load_season_stats()

    stats["last_updated"]     = audit_result["game_date"]
    stats["total_challenges"] += audit_result["summary"]["total_challenges"]
    stats["total_overturned"] += audit_result["summary"]["overturned"]

    for team, day_stats in audit_result["team_stats"].items():
        s = stats["team_stats"].setdefault(team, {
            "challenges": 0, "overturned": 0, "missed_calls": 0
        })
        s["challenges"]  += day_stats.get("challenges", 0)
        s["overturned"]  += day_stats.get("overturned", 0)
        s["missed_calls"] += day_stats.get("missed_calls", 0)

    for umpire, day_u in audit_result["umpire_stats"].items():
        u = stats["umpire_stats"].setdefault(umpire, {"total": 0, "correct": 0})
        u["total"]   += day_u.get("total", 0)
        u["correct"] += day_u.get("correct", 0)

    # Recompute correct_rate
    for u in stats["umpire_stats"].values():
        u["correct_rate"] = u["correct"] / u["total"] if u["total"] else 0.0

    SEASON_STATS.write_text(json.dumps(stats, indent=2))
    log.info("Season stats updated → %s", SEASON_STATS)
    return stats
