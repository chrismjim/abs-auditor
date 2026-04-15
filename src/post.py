"""
ABS Auditor — X (Twitter) posting via Tweepy v4+ OAuth 1.0a.

Builds a 2-3 tweet thread:
  Tweet 1: daily card image + summary caption
  Tweet 2: top storyline reply
  Tweet 3: focus-team breakdown (if applicable)
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from datetime import date

import tweepy

from src.config import ACCOUNT_HANDLE, FOCUS_TEAM

log = logging.getLogger(__name__)


def _get_client() -> tuple[tweepy.Client, tweepy.API]:
    """
    Return (tweepy.Client, tweepy.API).
    Client is used for v2 tweet creation; API (v1.1) for media upload.
    """
    api_key    = os.environ["TWITTER_API_KEY"]
    api_secret = os.environ["TWITTER_API_SECRET"]
    acc_token  = os.environ["TWITTER_ACCESS_TOKEN"]
    acc_secret = os.environ["TWITTER_ACCESS_SECRET"]

    # v1.1 API — needed for media_upload
    auth = tweepy.OAuth1UserHandler(api_key, api_secret, acc_token, acc_secret)
    api_v1 = tweepy.API(auth, wait_on_rate_limit=True)

    # v2 client — for tweet creation with reply threading
    client = tweepy.Client(
        consumer_key=api_key,
        consumer_secret=api_secret,
        access_token=acc_token,
        access_token_secret=acc_secret,
        wait_on_rate_limit=True,
    )
    return client, api_v1


def _upload_media(api_v1: tweepy.API, image_path: Path) -> str:
    """Upload image via v1.1 endpoint, return media_id string."""
    media = api_v1.media_upload(filename=str(image_path))
    log.info("Uploaded media: %s → id=%s", image_path.name, media.media_id_string)
    return media.media_id_string


def _build_tweet1(audit_result: dict, game_date: date) -> str:
    summary      = audit_result["summary"]
    total        = summary["total_challenges"]
    overturn     = summary["overturned"]
    missed       = summary["missed_calls"]
    date_str     = game_date.strftime("%B %-d, %Y")
    mgr_challs   = audit_result.get("manager_challenges", [])
    mgr_count    = len(mgr_challs)
    mgr_over     = sum(1 for c in mgr_challs if c.get("outcome") == "correct_overturn")

    if summary["no_challenges"] and mgr_count == 0:
        return (
            f"No challenges yesterday — clean game. ⚾\n"
            f"#MLB #ABS #Statcast"
        )

    if summary["no_challenges"] and mgr_count > 0:
        # ABS not yet active / no ABS challenges — report manager challenges
        return (
            f"Challenge Audit — {date_str} ⚾\n"
            f"ABS: no challenges\n"
            f"Replay: {mgr_over}/{mgr_count} overturned\n"
            f"#{FOCUS_TEAM} #MLB #ABS #Statcast"
        )

    return (
        f"ABS Challenge Audit — {date_str} ⚾\n"
        f"{total} ABS challenge(s) | {overturn} overturned | {missed} missed call(s)\n"
        f"🟢 correct overturn | 🔴 missed call | ⚪ upheld correctly\n"
        f"#{FOCUS_TEAM} #MLB #ABS #Statcast"
    )


def _build_tweet2(audit_result: dict) -> str | None:
    stories = audit_result.get("storylines", [])
    mgr     = audit_result.get("manager_challenges", [])

    lines: list[str] = []
    lines.extend(stories[:2])

    # If no ABS storylines but manager challenges exist, summarise them
    if not lines and mgr:
        over   = [c for c in mgr if c.get("outcome") == "correct_overturn"]
        upheld = [c for c in mgr if c.get("outcome") == "correct_upheld"]
        lines.append(
            f"Replay challenges: {len(over)} overturned, {len(upheld)} upheld."
        )
        # Most interesting overturn
        if over:
            c = over[0]
            subtype = c.get("challenge_subtype", "")
            lines.append(
                f"Notable: {c.get('challenger', '?')} ({subtype}) — overturned."
            )

    return "\n".join(lines) if lines else None


def _build_tweet3(audit_result: dict, game_date: date) -> str | None:
    focus_abs = audit_result.get("focus_abs", [])
    if not focus_abs:
        return None

    lines = [f"{FOCUS_TEAM} challenge breakdown:"]
    for ch in focus_abs[:4]:
        pitcher = ch.get("pitcher", "?")
        batter  = ch.get("batter", "?")
        inning  = ch.get("inning", "?")
        half    = "T" if ch.get("half_inning") == "top" else "B"
        outcome_label = {
            "correct_overturn":   "✅ Overturned (correct)",
            "incorrect_overturn": "⚠️ Overturned (was right)",
            "correct_upheld":     "✅ Upheld (correct)",
            "missed_call":        "❌ Upheld (missed call)",
        }.get(ch.get("outcome") or "", "— unknown")

        dist = ch.get("edge_dist")
        dist_str = f"  {abs(dist)*12:.1f}\" from edge" if dist is not None else ""

        lines.append(f"• {half}{inning}  {pitcher} → {batter}: {outcome_label}{dist_str}")

    return "\n".join(lines)


def _season_totals_line(audit_result: dict) -> str:
    # Caller should pass season stats but we fall back gracefully
    return "Season totals available in data/season_stats.json"


def post_thread(audit_result: dict, images: dict, game_date: date,
                dry_run: bool = True) -> list[str]:
    """
    Post the full thread.

    dry_run=True (default) — logs tweet text and saves images but does NOT post.
    Returns list of tweet IDs (or fake IDs in dry-run mode).
    """
    tweet1_text = _build_tweet1(audit_result, game_date)
    tweet2_text = _build_tweet2(audit_result)
    tweet3_text = _build_tweet3(audit_result, game_date)

    daily_card  = images.get("daily_card")
    leaderboard = images.get("leaderboard")

    if dry_run:
        log.info("=== DRY RUN — no tweets will be posted ===")
        log.info("── Tweet 1 ──\n%s", tweet1_text)
        if tweet2_text:
            log.info("── Tweet 2 ──\n%s", tweet2_text)
        if tweet3_text:
            log.info("── Tweet 3 ──\n%s", tweet3_text)
        if daily_card:
            log.info("Image 1: %s", daily_card)
        if leaderboard:
            log.info("Image 2: %s", leaderboard)
        return ["dry-run-id-1", "dry-run-id-2", "dry-run-id-3"]

    # ── Live posting ──────────────────────────────────────────────────────
    try:
        client, api_v1 = _get_client()
    except KeyError as exc:
        raise RuntimeError(
            f"Missing Twitter credential env var: {exc}. "
            "Set TWITTER_API_KEY, TWITTER_API_SECRET, "
            "TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_SECRET."
        ) from exc

    tweet_ids: list[str] = []

    # ── Tweet 1: daily card image + caption ───────────────────────────────
    media_ids: list[str] = []
    if daily_card and daily_card.exists():
        try:
            mid = _upload_media(api_v1, daily_card)
            media_ids.append(mid)
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

    # ── Tweet 2: storyline reply ───────────────────────────────────────────
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

    # ── Tweet 3: focus team breakdown ─────────────────────────────────────
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

    # ── Leaderboard reply (Mondays) ────────────────────────────────────────
    if leaderboard and leaderboard.exists():
        try:
            lb_mid = _upload_media(api_v1, leaderboard)
            lb_text = (
                f"Season challenge leaderboard as of {game_date.strftime('%B %-d')} ⚾\n"
                f"#{FOCUS_TEAM} #MLB #ABS #Statcast"
            )
            lb = client.create_tweet(
                text=lb_text,
                in_reply_to_tweet_id=tweet_ids[0],
                media_ids=[lb_mid],
            )
            lb_id = str(lb.data["id"])
            tweet_ids.append(lb_id)
            log.info("Posted leaderboard tweet: id=%s", lb_id)
        except Exception as exc:
            log.warning("Failed to post leaderboard tweet: %s", exc)

    return tweet_ids


def post_error_tweet(message: str, dry_run: bool = True) -> None:
    """Post a brief failure notification so you know the pipeline broke."""
    text = f"⚠️ ABS Auditor pipeline failed:\n{message[:200]}"
    if dry_run:
        log.info("DRY RUN error tweet:\n%s", text)
        return
    try:
        client, _ = _get_client()
        client.create_tweet(text=text)
    except Exception as exc:
        log.error("Could not post error tweet: %s", exc)
