"""
ABS Auditor — X (Twitter) posting via Tweepy v4+ OAuth 1.0a.

Single tweet per game (card image attached):
  • Narrative headline (biggest miss or clean-game note)
  • Umpire accuracy summary
  • Hashtags
  All visual detail (zone diagrams, counts, full ump stats) lives in the card.

+ Leaderboard reply on Mondays (separate tweet replying to the game post).
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
    """Return '#AWAY #HOME' from 'AWAY @ HOME'."""
    if matchup and " @ " in matchup:
        away, _, home = matchup.partition(" @ ")
        return f"#{away.strip()} #{home.strip()}"
    return ""


def build_tweet(audit_result: dict, game_date: date) -> str:
    """
    Single-tweet text (~150–200 chars):
      Line 1: AWAY @ HOME ⚾ M/D
      Line 2: Narrative headline (biggest miss / clean game / wrong overturn)
      Line 3: Ump accuracy (last name, %, wrong calls if any)
      Line 4: Hashtags
    """
    summary  = audit_result.get("summary", {})
    matchup  = audit_result.get("matchup", "")
    ua       = audit_result.get("ump_accuracy", {}) or {}
    abs_ch   = audit_result.get("abs_challenges", [])
    mgr      = audit_result.get("manager_challenges", [])
    mgr_over = sum(1 for c in mgr if c.get("outcome") == "correct_overturn")
    date_str = game_date.strftime("%-m/%-d")
    tags     = _team_tags(matchup)

    header = f"{matchup} ⚾ {date_str}" if matchup else f"MLB ABS Audit ⚾ {date_str}"

    # ── Narrative headline ────────────────────────────────────────────────────
    missed_ch  = [c for c in abs_ch if c.get("outcome") == "missed_call"
                  and c.get("edge_dist") is not None]
    worst_miss = max(missed_ch, key=lambda c: abs(c["edge_dist"])) if missed_ch else None
    wrong_over = next((c for c in abs_ch if c.get("outcome") == "incorrect_overturn"), None)

    if summary.get("no_challenges") and not mgr:
        headline = "No ABS challenges — clean game ✓"
    elif summary.get("no_challenges") and mgr:
        headline = f"No ABS challenges. Replay: {mgr_over}/{len(mgr)} overturned."
    elif worst_miss:
        d_in    = abs(worst_miss["edge_dist"]) * 12
        half    = "T" if worst_miss.get("half_inning") == "top" else "B"
        inn     = worst_miss.get("inning", "?")
        cnt     = worst_miss.get("count") or {}
        b, s    = cnt.get("balls"), cnt.get("strikes")
        cnt_str = f" {b}-{s}" if b is not None else ""
        batter  = (worst_miss.get("batter") or "?").split()[-1]
        pitcher = (worst_miss.get("pitcher") or "?").split()[-1]
        orig    = (worst_miss.get("original_call") or "").lower()
        call_w  = "called strike" if "called strike" in orig else "called ball"
        headline = (
            f"🔴 {pitcher} → {batter} ({half}{inn}{cnt_str}): "
            f"{call_w} {d_in:.1f}\" outside the zone — challenge denied"
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
            f"✅ {total} challenge{'s' if total != 1 else ''} — "
            f"{overturn} overturned, {missed} missed"
        )

    # ── Umpire accuracy line ──────────────────────────────────────────────────
    ump_name = ua.get("name")
    ump_pct  = ua.get("accuracy_pct")
    ump_tot  = ua.get("total_called", 0)
    ws       = ua.get("wrong_strikes", 0)
    wb       = ua.get("wrong_balls", 0)

    ump_line = ""
    if ump_name and ump_tot >= 5 and ump_pct is not None:
        last = ump_name.split()[-1]
        ump_line = f"Ump {last}: {ump_pct:.0f}% accurate"
        err_parts = []
        if ws:
            err_parts.append(f"{ws} wrong strike{'s' if ws != 1 else ''}")
        if wb:
            err_parts.append(f"{wb} wrong ball{'s' if wb != 1 else ''}")
        if err_parts:
            ump_line += " — " + ", ".join(err_parts)

    parts = [header, headline]
    if ump_line:
        parts.append(ump_line)
    parts.append((tags + " #MLB #ABS").strip() if tags else "#MLB #ABS")

    return "\n".join(parts)


def post_thread(audit_result: dict, images: dict, game_date: date,
                dry_run: bool = True) -> list[str]:
    """
    Post one tweet (with card image) for the completed game.
    On Mondays, also reply with ump leaderboard and trend chart.
    Returns list of tweet IDs posted.
    """
    tweet_text   = build_tweet(audit_result, game_date)
    daily_card   = images.get("daily_card")
    abs_lb       = images.get("leaderboard")
    ump_lb       = images.get("ump_leaderboard")
    trend        = images.get("trend")

    if dry_run:
        log.info("=== DRY RUN — no tweets posted ===")
        log.info("── Tweet ──\n%s", tweet_text)
        log.info("Char count: %d", len(tweet_text))
        for label, img in [("Card", daily_card), ("ABS LB", abs_lb),
                           ("Ump LB", ump_lb), ("Trend", trend)]:
            if img:
                log.info("%s: %s", label, img)
        return ["dry-run-id-1"]

    # ── Live posting ──────────────────────────────────────────────────────────
    try:
        client, api_v1 = _get_client()
    except KeyError as exc:
        raise RuntimeError(
            f"Missing Twitter credential: {exc}. "
            "Set TWITTER_API_KEY / SECRET and TWITTER_ACCESS_TOKEN / SECRET."
        ) from exc

    tweet_ids: list[str] = []

    # ── Main game tweet with card image ───────────────────────────────────────
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
        t1 = client.create_tweet(text=tweet_text, **kwargs)
        t1_id = str(t1.data["id"])
        tweet_ids.append(t1_id)
        log.info("Posted tweet: id=%s", t1_id)
    except Exception as exc:
        log.error("Failed to post tweet: %s", exc)
        raise

    date_str = game_date.strftime("%-m/%-d/%Y")

    # ── ABS challenge leaderboard reply (Mondays) ─────────────────────────────
    if abs_lb and Path(abs_lb).exists():
        try:
            lb_mid  = _upload_media(api_v1, Path(abs_lb))
            lb_text = f"ABS challenge leaderboard — {date_str} ⚾\n#MLB #ABS"
            lb = client.create_tweet(
                text=lb_text,
                in_reply_to_tweet_id=tweet_ids[0],
                media_ids=[lb_mid],
            )
            tweet_ids.append(str(lb.data["id"]))
            log.info("Posted ABS leaderboard reply: id=%s", lb.data["id"])
        except Exception as exc:
            log.warning("Failed to post ABS leaderboard: %s", exc)

    # ── Umpire accuracy leaderboard reply (Mondays) ───────────────────────────
    if ump_lb and Path(ump_lb).exists():
        try:
            ul_mid  = _upload_media(api_v1, Path(ump_lb))
            ul_text = (
                f"HP umpire accuracy leaderboard — {date_str} ⚾\n"
                f"Called-pitch accuracy (wrong strikes + wrong balls) · 2026 season\n"
                f"#MLB #ABS #Umpires"
            )
            reply_to = tweet_ids[-1]
            ul = client.create_tweet(
                text=ul_text,
                in_reply_to_tweet_id=reply_to,
                media_ids=[ul_mid],
            )
            tweet_ids.append(str(ul.data["id"]))
            log.info("Posted ump leaderboard reply: id=%s", ul.data["id"])
        except Exception as exc:
            log.warning("Failed to post ump leaderboard: %s", exc)

    # ── Trend chart reply (Mondays) ───────────────────────────────────────────
    if trend and Path(trend).exists():
        try:
            tr_mid  = _upload_media(api_v1, Path(trend))
            tr_text = (
                f"MLB ump accuracy + ABS overturn rate trend — {date_str} ⚾\n"
                f"#MLB #ABS"
            )
            reply_to = tweet_ids[-1]
            tr = client.create_tweet(
                text=tr_text,
                in_reply_to_tweet_id=reply_to,
                media_ids=[tr_mid],
            )
            tweet_ids.append(str(tr.data["id"]))
            log.info("Posted trend chart reply: id=%s", tr.data["id"])
        except Exception as exc:
            log.warning("Failed to post trend chart: %s", exc)

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
