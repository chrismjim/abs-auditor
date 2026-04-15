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
    summary  = audit_result.get("summary", {})
    matchup  = audit_result.get("matchup", "")
    total    = summary.get("total_challenges", 0)
    overturn = summary.get("overturned", 0)
    missed   = summary.get("missed_calls", 0)
    date_str = game_date.strftime("%B %-d, %Y")
    tags     = _team_tags(matchup)
    mgr      = audit_result.get("manager_challenges", [])
    mgr_over = sum(1 for c in mgr if c.get("outcome") == "correct_overturn")

    header = f"{matchup} — " if matchup else ""

    if summary.get("no_challenges") and not mgr:
        return (
            f"{header}ABS Audit ⚾\n"
            f"{date_str}\n\n"
            f"No challenges this game — clean game.\n"
            f"{tags} #MLB #ABS"
        ).strip()

    if summary.get("no_challenges") and mgr:
        return (
            f"{header}ABS Audit ⚾\n"
            f"{date_str}\n\n"
            f"No ABS challenges.\n"
            f"Replay: {mgr_over}/{len(mgr)} overturned.\n"
            f"{tags} #MLB #ABS"
        ).strip()

    return (
        f"{header}ABS Challenge Audit ⚾\n"
        f"{date_str}\n\n"
        f"{total} challenge{'s' if total != 1 else ''}  ·  "
        f"{overturn} overturned  ·  "
        f"{missed} missed call{'s' if missed != 1 else ''}\n"
        f"🟢 correct overturn  🔴 missed call  ⚪ upheld\n"
        f"{tags} #MLB #ABS #Statcast"
    ).strip()


def _build_tweet2(audit_result: dict) -> str | None:
    """Storylines + manager challenge highlights."""
    stories = audit_result.get("storylines", [])
    mgr     = audit_result.get("manager_challenges", [])
    lines: list[str] = list(stories[:3])

    # Summarise manager challenges if no ABS storylines
    if not lines and mgr:
        over   = [c for c in mgr if c.get("outcome") == "correct_overturn"]
        upheld = [c for c in mgr if c.get("outcome") == "correct_upheld"]
        lines.append(f"Replay challenges: {len(over)} overturned, {len(upheld)} upheld.")
        if over:
            c = over[0]
            lines.append(
                f"Notable: {c.get('challenger','?')} "
                f"({c.get('challenge_subtype','')}) — overturned."
            )

    return "\n".join(lines) if lines else None


def _build_tweet3(audit_result: dict) -> str | None:
    """
    Pitch-by-pitch breakdown for games with ≥ 2 ABS challenges.
    Replaces the old focus-team breakdown.
    """
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
    for ch in challs[:5]:
        half    = "T" if ch.get("half_inning") == "top" else "B"
        inn     = ch.get("inning", "?")
        pitcher = ch.get("pitcher", "?").split()[-1]
        batter  = ch.get("batter", "?").split()[-1]
        outcome = ch.get("outcome") or ""
        icon    = outcome_icon.get(outcome, "⚪")
        edge_d  = ch.get("edge_dist")

        dist_str = ""
        if edge_d is not None:
            d_in = abs(edge_d) * 12
            loc  = "in" if edge_d > 0 else "out"
            dist_str = f" ({d_in:.1f}\" {loc})"

        lines.append(f"• {half}{inn}  {pitcher} → {batter}: {icon}{dist_str}")

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
