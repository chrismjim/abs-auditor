"""
ABS Auditor — X (Twitter) posting via Tweepy v4+ OAuth 1.0a.

Per-game thread (up to 3 tweets):
  Tweet 1: game card image + headline stats
  Tweet 2: storylines / notable plays
  Tweet 3: pitch-by-pitch breakdown (if ≥ 2 ABS challenges)
  + Leaderboard reply on Mondays
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from datetime import date

import tweepy

log = logging.getLogger(__name__)


def _get_client() -> tuple[tweepy.Client, tweepy.API]:
    """Return (tweepy.Client v2, tweepy.API v1.1)."""
    api_key    = os.environ["TWITTER_API_KEY"]
    api_secret = os.environ["TWITTER_API_SECRET"]
    acc_token  = os.environ["TWITTER_ACCESS_TOKEN"]
    acc_secret = os.environ["TWITTER_ACCESS_SECRET"]

    auth = tweepy.OAuth1UserHandler(api_key, api_secret, acc_token, acc_secret)
    api_v1 = tweepy.API(auth, wait_on_rate_limit=True)

    client = tweepy.Client(
        consumer_key=api_key,
        consumer_secret=api_secret,
        access_token=acc_token,
        access_token_secret=acc_secret,
        wait_on_rate_limit=True,
    )
    return client, api_v1


def _upload_media(api_v1: tweepy.API, image_path: Path) -> str:
    media = api_v1.media_upload(filename=str(image_path))
    log.info("Uploaded media: %s → id=%s", image_path.name, media.media_id_string)
    return media.media_id_string


def _team_tags(matchup: str | None) -> str:
    """Return '#AWAY #HOME' hashtags from 'AWAY @ HOME' string."""
    if matchup and " @ " in matchup:
        away, _, home = matchup.partition(" @ ")
        return f"#{away.strip()} #{home.strip()}"
    return ""


def _build_tweet1(audit_result: dict, game_date: date) -> str:
    """
    Narrative-lead tweet. Headline = the most interesting single finding.
    Umpire accuracy appended as the second line.
    """
    summary  = audit_result.get("summary", {})
    matchup  = audit_result.get("matchup", "")
    ua       = audit_result.get("ump_accuracy", {}) or {}
    abs_ch   = audit_result.get("abs_challenges", [])
    mgr      = audit_result.get("manager_challenges", [])
    mgr_over = sum(1 for c in mgr if c.get("outcome") == "correct_overturn")
    date_str = game_date.strftime("%B %-d, %Y")
    tags     = _team_tags(matchup)
    header   = f"{matchup} | " if matchup else ""

    # ── Umpire accuracy line ──────────────────────────────────────────────────
    ump_name = ua.get("name")
    ump_tot  = ua.get("total_called", 0)
    ump_cor  = ua.get("correct", 0)
    ump_pct  = ua.get("accuracy_pct")
    ws       = ua.get("wrong_strikes", 0)
    wb       = ua.get("wrong_balls", 0)

    ump_line = ""
    if ump_name and ump_tot >= 5 and ump_pct is not None:
        ump_str = f"HP Ump {ump_name}: {ump_cor}/{ump_tot} correct ({ump_pct:.0f}%)"
        err_parts = []
        if ws:
            err_parts.append(f"{ws} wrong strike{'s' if ws != 1 else ''}")
        if wb:
            err_parts.append(f"{wb} wrong ball{'s' if wb != 1 else ''}")
        if err_parts:
            ump_str += " — " + ", ".join(err_parts)
        ump_line = ump_str

    # ── Key narrative headline ────────────────────────────────────────────────
    # Find biggest missed call
    missed_ch = [c for c in abs_ch if c.get("outcome") == "missed_call"
                 and c.get("edge_dist") is not None]
    worst_miss = max(missed_ch, key=lambda c: abs(c["edge_dist"])) if missed_ch else None

    # Find any incorrect overturn
    wrong_over = next((c for c in abs_ch if c.get("outcome") == "incorrect_overturn"), None)

    if summary.get("no_challenges") and not mgr:
        headline = "No ABS challenges — clean game ✓"
    elif summary.get("no_challenges") and mgr:
        headline = f"No ABS challenges. Replay: {mgr_over}/{len(mgr)} overturned."
    elif worst_miss:
        d_in     = abs(worst_miss["edge_dist"]) * 12
        half     = "T" if worst_miss.get("half_inning") == "top" else "B"
        inn      = worst_miss.get("inning", "?")
        cnt      = worst_miss.get("count") or {}
        b, s     = cnt.get("balls"), cnt.get("strikes")
        cnt_str  = f", {b}-{s}" if b is not None else ""
        batter   = (worst_miss.get("batter") or "?").split()[-1]
        pitcher  = (worst_miss.get("pitcher") or "?").split()[-1]
        orig     = (worst_miss.get("original_call") or "").lower()
        call_w   = "called strike" if "called strike" in orig else "called ball"
        headline = (
            f"🔴 {pitcher} → {batter} ({half}{inn}{cnt_str}): "
            f"{call_w} was {d_in:.1f}\" outside the zone — challenge denied"
        )
    elif wrong_over:
        half    = "T" if wrong_over.get("half_inning") == "top" else "B"
        inn     = wrong_over.get("inning", "?")
        batter  = (wrong_over.get("batter") or "?").split()[-1]
        pitcher = (wrong_over.get("pitcher") or "?").split()[-1]
        headline = f"🟡 {pitcher} → {batter} ({half}{inn}): ABS overturned a correct call"
    else:
        total    = summary.get("total_challenges", 0)
        overturn = summary.get("overturned", 0)
        missed   = summary.get("missed_calls", 0)
        headline = (
            f"{total} challenge{'s' if total != 1 else ''} — "
            f"{overturn} overturned, {missed} missed"
        )

    parts = [f"{header}ABS Audit ⚾  {date_str}", "", headline]
    if ump_line:
        parts.append(ump_line)
    if tags:
        parts.append(tags + " #MLB #ABS")
    else:
        parts.append("#MLB #ABS")

    return "\n".join(parts).strip()


def _build_tweet2(audit_result: dict) -> str | None:
    """
    Full umpire accuracy breakdown + ABS challenge summary.
    """
    ua      = audit_result.get("ump_accuracy", {}) or {}
    abs_ch  = audit_result.get("abs_challenges", [])
    mgr     = audit_result.get("manager_challenges", [])
    summary = audit_result.get("summary", {})

    lines: list[str] = []

    # Umpire breakdown
    ump_name = ua.get("name")
    ump_tot  = ua.get("total_called", 0)
    ump_cor  = ua.get("correct", 0)
    ump_pct  = ua.get("accuracy_pct")
    ws       = ua.get("wrong_strikes", 0)
    wb       = ua.get("wrong_balls", 0)

    if ump_name and ump_tot >= 5 and ump_pct is not None:
        lines.append(f"HP Umpire: {ump_name}")
        lines.append(f"✅ {ump_cor}/{ump_tot} called pitches correct ({ump_pct:.0f}%)")
        if ws:
            lines.append(f"❌ {ws} called strike{'s' if ws != 1 else ''} outside the zone")
        if wb:
            lines.append(f"❌ {wb} called ball{'s' if wb != 1 else ''} inside the zone")

    # ABS challenge breakdown
    if abs_ch:
        total    = summary.get("total_challenges", 0)
        overturn = summary.get("overturned", 0)
        upheld   = summary.get("correct_upheld", 0)
        missed   = summary.get("missed_calls", 0)
        if lines:
            lines.append("")
        lines.append(f"ABS: {total} challenge{'s' if total != 1 else ''}")
        lines.append(f"🟢 {overturn} overturned  ⚪ {upheld} upheld  🔴 {missed} missed")

    # Manager/replay challenges
    if mgr:
        mgr_over   = sum(1 for c in mgr if c.get("outcome") == "correct_overturn")
        mgr_upheld = sum(1 for c in mgr if c.get("outcome") == "correct_upheld")
        if lines:
            lines.append("")
        lines.append(f"Replay: {len(mgr)} challenge{'s' if len(mgr) != 1 else ''} — "
                     f"{mgr_over} overturned, {mgr_upheld} upheld")

    return "\n".join(lines) if lines else None


def _build_tweet3(audit_result: dict) -> str | None:
    """Pitch-by-pitch ABS challenge breakdown (games with ≥ 2 challenges)."""
    challs = audit_result.get("abs_challenges", [])
    if len(challs) < 2:
        return None

    outcome_icon = {
        "correct_overturn":   "🟢",
        "incorrect_overturn": "🟡",
        "correct_upheld":     "⚪",
        "missed_call":        "🔴",
    }

    lines = ["Challenge breakdown:"]
    for ch in challs[:6]:
        half    = "T" if ch.get("half_inning") == "top" else "B"
        inn     = ch.get("inning", "?")
        pitcher = (ch.get("pitcher") or "?").split()[-1]
        batter  = (ch.get("batter") or "?").split()[-1]
        outcome = ch.get("outcome") or ""
        icon    = outcome_icon.get(outcome, "⚪")
        edge_d  = ch.get("edge_dist")
        cnt     = ch.get("count") or {}
        b, s    = cnt.get("balls"), cnt.get("strikes")
        cnt_str = f" {b}-{s}" if b is not None else ""

        dist_str = ""
        if edge_d is not None:
            d_in = abs(edge_d) * 12
            loc  = "inside zone" if edge_d > 0 else "outside zone"
            dist_str = f" — {d_in:.1f}\" {loc}"

        lines.append(f"• {half}{inn}{cnt_str}  {pitcher}→{batter}: {icon}{dist_str}")

    return "\n".join(lines)


def post_thread(audit_result: dict, images: dict, game_date: date,
                dry_run: bool = True) -> list[str]:
    """
    Post the full thread for one game.
    dry_run=True (default) — logs content but does NOT post.
    Returns list of tweet IDs.
    """
    tweet1_text = _build_tweet1(audit_result, game_date)
    tweet2_text = _build_tweet2(audit_result)
    tweet3_text = _build_tweet3(audit_result)

    daily_card  = images.get("daily_card")
    leaderboard = images.get("leaderboard")

    if dry_run:
        log.info("=== DRY RUN — no tweets posted ===")
        log.info("── Tweet 1 ──\n%s", tweet1_text)
        if tweet2_text:
            log.info("── Tweet 2 ──\n%s", tweet2_text)
        if tweet3_text:
            log.info("── Tweet 3 ──\n%s", tweet3_text)
        if daily_card:
            log.info("Image: %s", daily_card)
        if leaderboard:
            log.info("Leaderboard: %s", leaderboard)
        return ["dry-run-id-1", "dry-run-id-2", "dry-run-id-3"]

    # ── Live posting ──────────────────────────────────────────────────────────
    try:
        client, api_v1 = _get_client()
    except KeyError as exc:
        raise RuntimeError(
            f"Missing Twitter credential: {exc}. "
            "Set TWITTER_API_KEY / SECRET and TWITTER_ACCESS_TOKEN / SECRET."
        ) from exc

    tweet_ids: list[str] = []

    # Tweet 1: card image + stats
    media_ids: list[str] = []
    if daily_card and Path(daily_card).exists():
        try:
            media_ids.append(_upload_media(api_v1, Path(daily_card)))
        except Exception as exc:
            log.warning("Media upload failed: %s", exc)

    try:
        kwargs: dict = {}
        if media_ids:
            kwargs["media_ids"] = media_ids
        t1 = client.create_tweet(text=tweet1_text, **kwargs)
        t1_id = str(t1.data["id"])
        tweet_ids.append(t1_id)
        log.info("Posted tweet 1: id=%s", t1_id)
    except Exception as exc:
        log.error("Failed to post tweet 1: %s", exc)
        raise

    # Tweet 2: storylines
    if tweet2_text:
        try:
            t2 = client.create_tweet(
                text=tweet2_text,
                in_reply_to_tweet_id=tweet_ids[-1],
            )
            t2_id = str(t2.data["id"])
            tweet_ids.append(t2_id)
            log.info("Posted tweet 2: id=%s", t2_id)
        except Exception as exc:
            log.warning("Failed to post tweet 2: %s", exc)

    # Tweet 3: pitch-by-pitch breakdown
    if tweet3_text:
        try:
            t3 = client.create_tweet(
                text=tweet3_text,
                in_reply_to_tweet_id=tweet_ids[-1],
            )
            t3_id = str(t3.data["id"])
            tweet_ids.append(t3_id)
            log.info("Posted tweet 3: id=%s", t3_id)
        except Exception as exc:
            log.warning("Failed to post tweet 3: %s", exc)

    # Leaderboard reply (Mondays)
    if leaderboard and Path(leaderboard).exists():
        try:
            lb_mid = _upload_media(api_v1, Path(leaderboard))
            lb_text = (
                f"Season ABS challenge leaderboard — "
                f"{game_date.strftime('%B %-d, %Y')} ⚾\n"
                f"#MLB #ABS #Statcast"
            )
            lb = client.create_tweet(
                text=lb_text,
                in_reply_to_tweet_id=tweet_ids[0],
                media_ids=[lb_mid],
            )
            tweet_ids.append(str(lb.data["id"]))
            log.info("Posted leaderboard: id=%s", lb.data["id"])
        except Exception as exc:
            log.warning("Failed to post leaderboard: %s", exc)

    return tweet_ids


def post_error_tweet(message: str, dry_run: bool = True) -> None:
    """Post a brief failure notification."""
    text = f"⚠️ ABS Auditor pipeline error:\n{message[:200]}"
    if dry_run:
        log.info("DRY RUN error tweet:\n%s", text)
        return
    try:
        client, _ = _get_client()
        client.create_tweet(text=text)
    except Exception as exc:
        log.error("Could not post error tweet: %s", exc)
