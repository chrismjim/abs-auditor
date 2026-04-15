"""
ABS Auditor — data fetching layer.

Pulls from:
  1. MLB Stats API  (game schedule + play-by-play)
  2. Baseball Savant CSV  (pitch-level Statcast data)
  3. pybaseball  (fallback / historical supplement)

─────────────────────────────────────────────────────────────────────────────
ABS CHALLENGE DATA — HOW IT ACTUALLY WORKS (verified 2026-04-14)
─────────────────────────────────────────────────────────────────────────────
The MLB Stats API encodes ALL reviews (ABS + manager replay) the same way:

    about.hasReview == True
    about.challengeType  ← None / not present in 2026

Differentiation is entirely in result.description:

  ABS challenge:      "[Batter] challenged (pitch result), call on the field
                       was confirmed/overturned: [at-bat result]."
  Manager replay:     "[Team] challenged (play at 1st|tag play|...), call on
                       the field was upheld/overturned: ..."
  Umpire review:      "Umpire reviewed (home run|...), call on the field was ..."

So (pitch result) == ABS challenge.  All other subtypes == manager/umpire.

For pitch location we cross-reference the Statcast CSV (plate_x, plate_z,
sz_top, sz_bot) by matching game_pk + at_bat_number from the play-by-play.

Season-level ABS stats are also available at:
  /leaderboard/abs-challenges?csv=true&year=YYYY&type=batter|pitcher
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import io
import logging
import re
import time
from datetime import date
from typing import Any

import pandas as pd
import requests

from src.config import (
    MAX_RETRIES,
    MLB_API_BASE,
    RETRY_BACKOFF_S,
    SAVANT_CSV_URL,
    ZONE_HALF_WIDTH_FT,
)

log = logging.getLogger(__name__)

# ── HTTP helpers ──────────────────────────────────────────────────────────────

def _get(url: str, params: dict | None = None, timeout: int = 30) -> requests.Response:
    """GET with retry logic and exponential-ish backoff."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = requests.get(url, params=params, timeout=timeout)
            r.raise_for_status()
            return r
        except requests.RequestException as exc:
            log.warning("Attempt %d/%d failed for %s: %s", attempt, MAX_RETRIES, url, exc)
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF_S * attempt)
            else:
                raise


# ── MLB Stats API ─────────────────────────────────────────────────────────────

def get_schedule(game_date: date) -> list[dict]:
    """Return list of game dicts for the given date."""
    date_str = game_date.strftime("%Y-%m-%d")
    url = f"{MLB_API_BASE}/schedule"
    params = {
        "sportId": 1,
        "date": date_str,
        "hydrate": "team,linescore,officials",
    }
    data = _get(url, params=params).json()
    games: list[dict] = []
    for date_block in data.get("dates", []):
        for g in date_block.get("games", []):
            games.append(g)
    log.info("Schedule: %d game(s) on %s", len(games), date_str)
    return games


def get_play_by_play(game_pk: int) -> dict:
    """Return full play-by-play payload for a single game."""
    url = f"{MLB_API_BASE}/game/{game_pk}/playByPlay"
    return _get(url).json()


# ── Challenge description parsing ─────────────────────────────────────────────

# Pattern: "[Team|Umpire] challenged|reviewed ([type]), call ... was [upheld|overturned]"
_CHALLENGE_RE = re.compile(
    r"^(?P<who>.+?)\s+(?P<verb>challenged|reviewed)\s+\((?P<type>[^)]+)\)"
    r".*?(?P<outcome>upheld|overturned|confirmed)",
    re.IGNORECASE,
)

def _parse_description(desc: str) -> dict | None:
    """
    Parse a result.description string from a hasReview play.

    ABS challenge:   "[Batter] challenged (pitch result), call ... confirmed/overturned"
    Manager replay:  "[Team] challenged (play at 1st|tag play|...), call ... upheld/overturned"
    Umpire review:   "Umpire reviewed (...), call ... upheld/overturned"

    The discriminator is the subtype in parentheses:
      "pitch result"  → absChallenge
      anything else   → managerChallenge or umpireReview
    """
    if not desc:
        return None

    m = _CHALLENGE_RE.search(desc)
    if not m:
        return None

    who      = m.group("who").strip()
    verb     = m.group("verb").lower()
    subtype  = m.group("type").strip().lower()   # "pitch result", "play at 1st", etc.
    outcome  = m.group("outcome").lower()        # "upheld"/"overturned"/"confirmed"
    overturned = (outcome == "overturned")

    # ABS = (pitch result).  Everything else is manager/umpire replay.
    if subtype == "pitch result":
        ctype = "absChallenge"
    elif verb == "reviewed":
        ctype = "umpireReview"
    else:
        ctype = "managerChallenge"

    return {
        "challenger":        who,
        "challenge_subtype": subtype,
        "overturned":        overturned,
        "challenge_type":    ctype,
    }


def extract_challenges(play_by_play: dict, game_pk: int) -> list[dict]:
    """
    Walk every play in the play-by-play and collect challenge/review events.

    Primary indicator: about.hasReview == True
    Secondary (future-proof): about.challengeType field if MLB adds it

    Returns a list of dicts, one per challenged play.
    """
    challenges: list[dict] = []
    all_plays = play_by_play.get("allPlays", [])

    for play in all_plays:
        about   = play.get("about", {})
        matchup = play.get("matchup", {})
        result  = play.get("result", {})

        # ── Primary path: hasReview ───────────────────────────────────────
        has_review     = about.get("hasReview", False)
        # Also check for a future challengeType field
        challenge_type_api = about.get("challengeType")  # None today

        if not has_review and not challenge_type_api:
            continue

        desc        = result.get("description", "")
        parsed      = _parse_description(desc)
        batter_id   = matchup.get("batter", {}).get("id")
        batter      = matchup.get("batter", {}).get("fullName", "Unknown")
        pitcher     = matchup.get("pitcher", {}).get("fullName", "Unknown")
        inning      = about.get("inning")
        half        = about.get("halfInning", "")
        at_bat_idx  = about.get("atBatIndex")

        if parsed:
            ctype      = challenge_type_api or parsed["challenge_type"]
            overturned = parsed["overturned"]
            subtype    = parsed["challenge_subtype"]
            challenger = parsed["challenger"]
        else:
            # hasReview=True but description didn't match pattern
            # (e.g., boundary call auto-review).  Still record it.
            ctype      = challenge_type_api or "umpireReview"
            overturned = None
            subtype    = "unknown"
            challenger = "Umpire"

        # ── Grab pitch data from the play's last pitch event (if any) ─────
        pitch_x = pitch_z = sz_top = sz_bot = None
        original_call = None
        for ev in reversed(play.get("playEvents", [])):
            if not ev.get("isPitch"):
                continue
            pd_api = ev.get("pitchData", {}) or {}
            coords = pd_api.get("coordinates", {}) or {}
            px  = coords.get("pX")
            pz  = coords.get("pZ")
            top = pd_api.get("strikeZoneTop")
            bot = pd_api.get("strikeZoneBottom")
            if px is not None and pz is not None:
                pitch_x = float(px)
                pitch_z = float(pz)
                sz_top  = float(top) if top is not None else None
                sz_bot  = float(bot) if bot is not None else None
                call_desc = ev.get("details", {}).get("description", "")
                original_call = call_desc
                break

        rec = {
            "game_pk":          game_pk,
            "at_bat_idx":       at_bat_idx,
            "inning":           inning,
            "half_inning":      half,
            "batter":           batter,
            "batter_id":        batter_id,
            "pitcher":          pitcher,
            "challenge_type":   ctype,
            "challenge_subtype": subtype,
            "challenger":       challenger,
            "overturned":       overturned,
            "description":      desc,
            "pitch_x":          pitch_x,
            "pitch_z":          pitch_z,
            "sz_top":           sz_top,
            "sz_bot":           sz_bot,
            "original_call":    original_call,
            "source":           "hasReview",
        }
        challenges.append(rec)

    return challenges


def infer_abs_candidates(play_by_play: dict, game_pk: int,
                          edge_threshold_ft: float = 2/12) -> list[dict]:
    """
    ABS inference fallback: scan every called pitch (called_strike / ball)
    and flag those within `edge_threshold_ft` (default 2 inches) of the
    strike zone edge.

    These are NOT confirmed ABS challenges — they are candidates for manual
    review or future matching when the API exposes the data.

    Returns a list of candidate dicts.
    """
    candidates: list[dict] = []
    all_plays = play_by_play.get("allPlays", [])

    for play in all_plays:
        matchup = play.get("matchup", {})
        about   = play.get("about", {})

        for ev in play.get("playEvents", []):
            if not ev.get("isPitch"):
                continue
            details = ev.get("details", {})
            call_desc = details.get("description", "").lower()

            is_called = "called strike" in call_desc or call_desc == "ball"
            if not is_called:
                continue

            pd_api = ev.get("pitchData", {}) or {}
            coords = pd_api.get("coordinates", {}) or {}
            px  = coords.get("pX")
            pz  = coords.get("pZ")
            top = pd_api.get("strikeZoneTop")
            bot = pd_api.get("strikeZoneBottom")

            if px is None or pz is None or top is None or bot is None:
                continue

            px, pz, top, bot = float(px), float(pz), float(top), float(bot)

            # Distance from each zone boundary
            dist_x   = ZONE_HALF_WIDTH_FT - abs(px)    # positive = inside
            dist_top = top - pz
            dist_bot = pz - bot
            dist_vert = min(dist_top, dist_bot)

            # Pitch is "on the edge" if within threshold of width OR height
            on_edge = (abs(dist_x) <= edge_threshold_ft or
                       abs(dist_vert) <= edge_threshold_ft)

            if not on_edge:
                continue

            candidates.append({
                "game_pk":        game_pk,
                "at_bat_idx":     about.get("atBatIndex"),
                "inning":         about.get("inning"),
                "half_inning":    about.get("halfInning"),
                "batter":         matchup.get("batter", {}).get("fullName", "?"),
                "batter_id":      matchup.get("batter", {}).get("id"),
                "pitcher":        matchup.get("pitcher", {}).get("fullName", "?"),
                "pitch_x":        px,
                "pitch_z":        pz,
                "sz_top":         top,
                "sz_bot":         bot,
                "original_call":  details.get("description", ""),
                "dist_from_edge": min(abs(dist_x), abs(dist_vert)),
                "source":         "abs_inferred",
            })

    return candidates


def get_umpire_crew(game: dict) -> str | None:
    """Extract plate umpire name from a game dict returned by the schedule."""
    officials = game.get("officials", [])
    for o in officials:
        if o.get("officialType") == "Home Plate":
            return o.get("official", {}).get("fullName")
    return None


# ── Baseball Savant ───────────────────────────────────────────────────────────

def get_savant_pitches(game_date: date) -> pd.DataFrame:
    """
    Pull pitch-level Statcast data for a date from Baseball Savant.

    Returns an empty DataFrame if no data is available (e.g. off-day).
    Savant data typically appears 8-10 AM ET the morning after games.
    """
    date_str = game_date.strftime("%Y-%m-%d")
    params = {
        "all":          "true",
        "hfGT":         "R|",
        "game_date_gt": date_str,
        "game_date_lt": date_str,
        "min_pitches":  "0",
        "min_results":  "0",
        "group_by":     "name",
        "sort_col":     "pitches",
        "player_event_sort": "api_p_release_speed",
        "sort_order":   "desc",
        "min_pas":      "0",
        "type":         "details",
    }
    log.info("Fetching Savant CSV for %s …", date_str)
    try:
        r = _get(SAVANT_CSV_URL, params=params, timeout=60)
    except requests.RequestException as exc:
        log.warning("Savant fetch failed: %s", exc)
        return pd.DataFrame()

    content = r.text.strip()
    if not content or content.startswith("Error") or len(content) < 200:
        log.info("Savant returned no pitch data for %s", date_str)
        return pd.DataFrame()

    try:
        df = pd.read_csv(io.StringIO(content), low_memory=False)
    except Exception as exc:
        log.warning("Failed to parse Savant CSV: %s", exc)
        return pd.DataFrame()

    log.info("Savant: %d pitches for %s", len(df), date_str)
    return df


def savant_for_batter(pitches_df: pd.DataFrame, batter_id: int,
                      inning: int, half: str) -> pd.DataFrame:
    """
    Narrow Savant pitch data to a specific batter / inning / half.
    """
    if pitches_df.empty:
        return pd.DataFrame()

    df = pitches_df.copy()
    filters = []
    if "batter" in df.columns:
        filters.append(df["batter"] == batter_id)
    if "inning" in df.columns and inning is not None:
        filters.append(df["inning"] == inning)
    if "inning_topbot" in df.columns and half:
        savant_half = "Top" if half == "top" else "Bot"
        filters.append(df["inning_topbot"] == savant_half)

    if not filters:
        return pd.DataFrame()
    mask = filters[0]
    for f in filters[1:]:
        mask = mask & f
    return df[mask]


# ── pybaseball fallback ───────────────────────────────────────────────────────

def get_statcast_pybaseball(game_date: date) -> pd.DataFrame:
    """Fallback: pull Statcast data via pybaseball."""
    try:
        from pybaseball import statcast  # type: ignore
        date_str = game_date.strftime("%Y-%m-%d")
        log.info("Fetching via pybaseball for %s …", date_str)
        df = statcast(start_dt=date_str, end_dt=date_str)
        log.info("pybaseball: %d rows", len(df) if df is not None else 0)
        return df if df is not None else pd.DataFrame()
    except Exception as exc:
        log.warning("pybaseball fallback failed: %s", exc)
        return pd.DataFrame()


def get_pitches(game_date: date) -> pd.DataFrame:
    """Primary entry point for pitch data. Tries Savant first, then pybaseball."""
    df = get_savant_pitches(game_date)
    if df.empty:
        log.info("Savant empty — trying pybaseball fallback")
        df = get_statcast_pybaseball(game_date)
    return df


def get_abs_leaderboard(year: int, entity_type: str = "batter") -> pd.DataFrame:
    """
    Fetch the season-to-date ABS challenge leaderboard from Savant.

    entity_type: "batter" or "pitcher"
    Returns a DataFrame with columns like entity_name, team_abbr,
    n_challenges, n_overturns, rate_overturns, etc.
    """
    url = "https://baseballsavant.mlb.com/leaderboard/abs-challenges"
    try:
        r = _get(url, params={"csv": "true", "year": str(year),
                              "type": entity_type}, timeout=30)
        df = pd.read_csv(io.StringIO(r.text))
        log.info("ABS leaderboard (%s, %d): %d rows", entity_type, year, len(df))
        return df
    except Exception as exc:
        log.warning("ABS leaderboard fetch failed: %s", exc)
        return pd.DataFrame()


def enrich_challenge_with_statcast(challenge: dict,
                                   pitches_df: pd.DataFrame) -> dict:
    """
    Look up the exact challenged pitch in the Statcast DataFrame using
    game_pk + at_bat_number, then copy plate_x/plate_z/sz_top/sz_bot.

    This is the primary enrichment path for ABS challenges — the play-by-play
    API's pitchData block usually covers it, but Statcast has more precise
    coordinates from the Hawkeye / TrackMan system.
    """
    if pitches_df.empty:
        return challenge
    if challenge.get("pitch_x") is not None:
        # Already have coords from play-by-play API; Statcast is supplemental
        return challenge

    game_pk   = challenge.get("game_pk")
    ab_number = challenge.get("at_bat_idx")   # play-by-play atBatIndex

    if game_pk is None or ab_number is None:
        return challenge

    # Statcast uses at_bat_number (1-based) which equals atBatIndex + 1
    needed_cols = {"game_pk", "at_bat_number", "plate_x", "plate_z", "sz_top", "sz_bot"}
    if not needed_cols.issubset(pitches_df.columns):
        return challenge

    subset = pitches_df[
        (pitches_df["game_pk"] == game_pk) &
        (pitches_df["at_bat_number"] == ab_number + 1)
    ]
    if subset.empty:
        return challenge

    # Take the last pitch of the at-bat (most likely the challenged call)
    row = subset.iloc[-1]
    for sc_col, ch_key in [("plate_x", "pitch_x"), ("plate_z", "pitch_z"),
                            ("sz_top", "sz_top"), ("sz_bot", "sz_bot")]:
        val = row.get(sc_col) if hasattr(row, "get") else (
            row[sc_col] if sc_col in row.index else None
        )
        import numpy as np
        if val is not None and not (isinstance(val, float) and np.isnan(val)):
            challenge[ch_key] = float(val)

    return challenge


# ── Top-level fetch orchestrator ──────────────────────────────────────────────

def fetch_day(game_date: date) -> tuple[list[dict], pd.DataFrame]:
    """
    Fetch everything needed for one day.

    Returns:
        challenges : list of raw challenge dicts (ABS + manager + umpire review)
        pitches_df : Statcast pitch DataFrame with plate_x/z coords (may be empty)
    """
    games = get_schedule(game_date)
    if not games:
        log.info("No games scheduled for %s", game_date)
        return [], pd.DataFrame()

    pitches_df = get_pitches(game_date)

    all_challenges: list[dict] = []
    for game in games:
        game_pk = game.get("gamePk")
        if not game_pk:
            continue

        status = game.get("status", {}).get("abstractGameState", "")
        if status not in ("Final", "Live"):
            log.debug("Skipping game %s — status: %s", game_pk, status)
            continue

        try:
            pbp = get_play_by_play(game_pk)
        except requests.RequestException as exc:
            log.warning("Could not fetch PBP for gamePk=%s: %s", game_pk, exc)
            continue

        challenges = extract_challenges(pbp, game_pk)
        umpire = get_umpire_crew(game)
        home   = game.get("teams", {}).get("home", {}).get("team", {}).get("abbreviation", "")
        away   = game.get("teams", {}).get("away", {}).get("team", {}).get("abbreviation", "")

        for ch in challenges:
            ch["home_team"] = home
            ch["away_team"] = away
            ch["umpire"]    = umpire
            ch["game_date"] = game_date.isoformat()

        log.info("gamePk=%s (%s @ %s): %d challenge(s)", game_pk, away, home, len(challenges))
        all_challenges.extend(challenges)

    return all_challenges, pitches_df
