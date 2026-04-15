"""
ABS Auditor — visualization (v2).

Per-game cards with:
  • Matchup header (AWAY @ HOME) with team colour accents
  • Strike zone panels with pitch location + edge-distance annotation
  • Team colour accent on each panel (batting team)
  • Outcome-coloured dots (brighter palette)
  • Clean summary bar and legend
  • Season leaderboard (Mondays / forced)
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import matplotlib
matplotlib.use("Agg")   # headless / no display
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from src.audit import (
    CORRECT_OVERTURN,
    CORRECT_UPHELD,
    INCORRECT_OVERTURN,
    MISSED_CALL,
)
from src.config import (
    COLORS,
    DPI,
    FIGURE_HEIGHT_PX,
    FIGURE_WIDTH_PX,
    MAX_CHALLENGES_ON_CARD,
    OUTPUT_DIR,
    TEAM_COLORS,
    ZONE_HALF_WIDTH_FT,
)

log = logging.getLogger(__name__)

FW = FIGURE_WIDTH_PX  / DPI
FH = FIGURE_HEIGHT_PX / DPI

OUTCOME_COLORS = {
    CORRECT_OVERTURN:   COLORS["correct"],
    INCORRECT_OVERTURN: COLORS["missed"],
    CORRECT_UPHELD:     COLORS["neutral"],
    MISSED_CALL:        COLORS["missed"],
    None:               COLORS["neutral"],
}

OUTCOME_LABELS = {
    CORRECT_OVERTURN:   "Correct Overturn",
    INCORRECT_OVERTURN: "Wrong Overturn",
    CORRECT_UPHELD:     "Upheld ✓",
    MISSED_CALL:        "Missed Call",
    None:               "—",
}

OUTCOME_ICONS = {
    CORRECT_OVERTURN:   "🟢",
    INCORRECT_OVERTURN: "🟡",
    CORRECT_UPHELD:     "⚪",
    MISSED_CALL:        "🔴",
    None:               "⚪",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _set_dark_bg(fig: plt.Figure, axes: list) -> None:
    fig.patch.set_facecolor(COLORS["bg"])
    for ax in axes:
        ax.set_facecolor(COLORS["bg"])


def _last_name(full: str | None) -> str:
    """Return last name (or full string if no space)."""
    if not full:
        return "?"
    parts = full.split()
    return parts[-1] if len(parts) > 1 else full


def _team_color(abbr: str | None) -> str:
    return TEAM_COLORS.get(abbr or "", COLORS["border"])


def _parse_matchup(matchup: str | None) -> tuple[str, str]:
    """Return (away_abbr, home_abbr) from 'AWAY @ HOME', or ('', '')."""
    if matchup and " @ " in matchup:
        away, _, home = matchup.partition(" @ ")
        return away.strip(), home.strip()
    return "", ""


# ── Strike zone panel ─────────────────────────────────────────────────────────

def draw_strike_zone(ax: plt.Axes, challenge: dict) -> None:
    """Draw strike zone box + pitch dot. Caller is responsible for ax limits."""
    sz_top = challenge.get("sz_top") or 3.5
    sz_bot = challenge.get("sz_bot") or 1.5
    px     = challenge.get("pitch_x")
    pz     = challenge.get("pitch_z")
    outcome = challenge.get("outcome")
    edge_d  = challenge.get("edge_dist")

    # Zone box
    zone = mpatches.FancyBboxPatch(
        (-ZONE_HALF_WIDTH_FT, sz_bot),
        ZONE_HALF_WIDTH_FT * 2, sz_top - sz_bot,
        boxstyle="square,pad=0",
        linewidth=1.4,
        edgecolor=COLORS["zone_edge"],
        facecolor=COLORS["zone_fill"],
        zorder=2,
    )
    ax.add_patch(zone)

    # Inner zone quadrant lines (subtle)
    mid_z = (sz_top + sz_bot) / 2
    ax.plot([-ZONE_HALF_WIDTH_FT, ZONE_HALF_WIDTH_FT], [mid_z, mid_z],
            color=COLORS["border"], linewidth=0.4, zorder=2)
    ax.plot([0, 0], [sz_bot, sz_top],
            color=COLORS["border"], linewidth=0.4, zorder=2)

    # Pitch dot
    if px is not None and pz is not None:
        dot_color = OUTCOME_COLORS.get(outcome, COLORS["neutral"])
        ax.scatter([px], [pz], s=90, color=dot_color, zorder=5,
                   linewidths=1.0, edgecolors="white")

        # Edge-distance annotation inside the panel
        if edge_d is not None:
            d_in = abs(edge_d) * 12
            loc  = "in" if edge_d > 0 else "out"
            ax.text(
                ZONE_HALF_WIDTH_FT + 0.33, sz_bot - 0.25,
                f"{d_in:.1f}\"",
                ha="right", va="top",
                color=COLORS["text_muted"],
                fontsize=5.5,
                zorder=6,
            )

    pad_x = 0.42
    pad_z = 0.52
    ax.set_xlim(-ZONE_HALF_WIDTH_FT - pad_x, ZONE_HALF_WIDTH_FT + pad_x)
    ax.set_ylim(sz_bot - pad_z, sz_top + pad_z)
    ax.set_aspect("equal")
    ax.axis("off")


# ── Header ────────────────────────────────────────────────────────────────────

def _draw_header(fig: plt.Figure, audit_result: dict, game_date: date) -> float:
    """
    Draw the matchup header and return the y-coordinate where content begins
    (i.e. where the panel grid should start from the top).
    """
    matchup  = audit_result.get("matchup", "")
    date_str = game_date.strftime("%B %-d, %Y").upper()
    away, home = _parse_matchup(matchup)

    if away and home:
        away_c = _team_color(away)
        home_c = _team_color(home)

        # Team colour accent bar spanning full width (split away | home)
        for x0, colour in [(0.0, away_c), (0.5, home_c)]:
            bar = mpatches.Rectangle(
                (x0, 0.892), 0.5, 0.009,
                transform=fig.transFigure,
                color=colour, alpha=0.9, zorder=4,
            )
            fig.add_artist(bar)

        # Away abbreviation (left-of-centre)
        fig.text(
            0.30, 0.950, away,
            ha="center", va="center",
            color=away_c,
            fontsize=26, fontweight="bold",
            transform=fig.transFigure,
        )
        # "@" separator
        fig.text(
            0.50, 0.948, "@",
            ha="center", va="center",
            color=COLORS["text_muted"],
            fontsize=18,
            transform=fig.transFigure,
        )
        # Home abbreviation (right-of-centre)
        fig.text(
            0.70, 0.950, home,
            ha="center", va="center",
            color=home_c,
            fontsize=26, fontweight="bold",
            transform=fig.transFigure,
        )
        # Sub-title: "ABS CHALLENGE AUDIT · DATE"
        fig.text(
            0.50, 0.905,
            f"ABS CHALLENGE AUDIT  ·  {date_str}",
            ha="center", va="center",
            color=COLORS["text_muted"],
            fontsize=9.5,
            transform=fig.transFigure,
        )
        content_top = 0.885

    else:
        # No matchup (batch / daily mode)
        fig.text(
            0.50, 0.950,
            "MLB ABS CHALLENGE AUDIT",
            ha="center", va="center",
            color=COLORS["text"],
            fontsize=16, fontweight="bold",
            transform=fig.transFigure,
        )
        fig.text(
            0.50, 0.910, date_str,
            ha="center", va="center",
            color=COLORS["text_muted"],
            fontsize=10,
            transform=fig.transFigure,
        )
        content_top = 0.890

    return content_top


# ── Summary bar + legend ──────────────────────────────────────────────────────

def _add_summary_bar(fig: plt.Figure, summary: dict, matchup: str = "",
                     ump_accuracy: dict | None = None) -> None:
    """
    Three-line footer:
      Line 1 — ABS challenge results
      Line 2 — Full-game umpire accuracy
      Line 3 — Data source
    """
    ua       = ump_accuracy or {}
    total    = summary.get("total_challenges", 0)
    overturn = summary.get("overturned", 0)
    missed   = summary.get("missed_calls", 0)
    upheld   = summary.get("correct_upheld", 0)

    # Line 1: ABS challenges
    if total == 0:
        abs_line = "No ABS challenges this game"
    else:
        abs_line = (
            f"ABS:  {total} challenge{'s' if total != 1 else ''}  ·  "
            f"{overturn} overturned  ·  "
            f"{missed} missed  ·  "
            f"{upheld} upheld"
        )
    fig.text(0.50, 0.132, abs_line,
             ha="center", va="center", color=COLORS["text"],
             fontsize=8.5, transform=fig.transFigure)

    # Line 2: Umpire full-game accuracy
    ump_name = ua.get("name")
    ump_tot  = ua.get("total_called", 0)
    ump_cor  = ua.get("correct", 0)
    ump_pct  = ua.get("accuracy_pct")
    ws       = ua.get("wrong_strikes", 0)
    wb       = ua.get("wrong_balls", 0)

    if ump_name and ump_tot >= 5 and ump_pct is not None:
        ump_detail = ""
        if ws or wb:
            parts = []
            if ws:
                parts.append(f"{ws} wrong strike{'s' if ws != 1 else ''}")
            if wb:
                parts.append(f"{wb} wrong ball{'s' if wb != 1 else ''}")
            ump_detail = "  (" + ", ".join(parts) + ")"
        ump_line = (
            f"HP Ump {ump_name}  ·  "
            f"{ump_cor}/{ump_tot} called pitches correct ({ump_pct:.0f}%)"
            f"{ump_detail}"
        )
        ump_color = COLORS["text"]
    elif ump_name:
        ump_line  = f"HP Ump: {ump_name}"
        ump_color = COLORS["text_muted"]
    else:
        ump_line  = ""
        ump_color = COLORS["text_muted"]

    if ump_line:
        fig.text(0.50, 0.090, ump_line,
                 ha="center", va="center", color=ump_color,
                 fontsize=8, transform=fig.transFigure)

    # Line 3: data source
    fig.text(0.50, 0.050,
             "Data: MLB Stats API  +  Baseball Savant / Statcast",
             ha="center", va="center", color=COLORS["text_muted"],
             fontsize=6.5, transform=fig.transFigure)


def _add_legend(fig: plt.Figure) -> None:
    items = [
        (COLORS["correct"], "Correct Overturn"),
        (COLORS["missed"],  "Missed Call / Wrong Overturn"),
        (COLORS["neutral"], "Upheld Correctly"),
    ]
    total_w = 0.80
    start_x = (1.0 - total_w) / 2
    step    = total_w / len(items)
    for i, (color, label) in enumerate(items):
        x = start_x + i * step + step / 2
        fig.text(x - 0.03, 0.183, "●", color=color, fontsize=10,
                 ha="right", va="center", transform=fig.transFigure)
        fig.text(x - 0.025, 0.183, label, color=COLORS["text_muted"],
                 fontsize=7, ha="left", va="center",
                 transform=fig.transFigure)


# ── Image 1: per-game audit card ──────────────────────────────────────────────

def make_game_card(audit_result: dict, game_date: date,
                   game_pk: int | None = None) -> Path:
    """
    Generate one game's ABS challenge card.
    game_pk is used to create a unique filename when multiple games are on the
    same date (live mode).
    """
    abs_challs = audit_result.get("abs_challenges", [])
    summary    = audit_result.get("summary", {})
    matchup    = audit_result.get("matchup", "")
    away, home = _parse_matchup(matchup)

    display_challs = abs_challs[:MAX_CHALLENGES_ON_CARD]
    n = len(display_challs)

    fig = plt.figure(figsize=(FW, FH), dpi=DPI)
    _set_dark_bg(fig, [])

    content_top = _draw_header(fig, audit_result, game_date)

    # ── No challenges ────────────────────────────────────────────────────────
    if n == 0:
        mgr        = audit_result.get("manager_challenges", [])
        mgr_over   = sum(1 for c in mgr if c.get("outcome") == CORRECT_OVERTURN)

        if mgr:
            body = (
                f"No ABS challenges this game.\n\n"
                f"Replay challenges: {mgr_over}/{len(mgr)} overturned."
            )
        else:
            body = "No challenges this game — clean game ✓"

        fig.text(
            0.50, 0.50, body,
            ha="center", va="center",
            color=COLORS["text_muted"],
            fontsize=14, fontstyle="italic",
            multialignment="center",
            transform=fig.transFigure,
        )
        _add_summary_bar(fig, summary, matchup,
                         ump_accuracy=audit_result.get("ump_accuracy", {}))
        _add_legend(fig)
        pk_suffix = f"_{game_pk}" if game_pk else ""
        out_path = OUTPUT_DIR / f"game_card_{game_date.isoformat()}{pk_suffix}.png"
        plt.savefig(out_path, dpi=DPI, bbox_inches="tight", facecolor=COLORS["bg"])
        plt.close(fig)
        log.info("Saved game card → %s", out_path)
        return out_path

    # ── Grid layout ──────────────────────────────────────────────────────────
    cols       = min(n, 3)
    rows       = (n + cols - 1) // cols
    grid_top   = content_top - 0.02
    grid_bot   = 0.215
    grid_h     = grid_top - grid_bot
    row_h      = grid_h / rows
    col_w      = 1.0 / cols

    zone_frac  = 0.57   # fraction of cell height for the zone ax
    label_frac = 0.38   # fraction of cell height for text below

    axes: list[plt.Axes] = []

    for idx, ch in enumerate(display_challs):
        row = idx // cols
        col = idx %  cols

        # Figure-coord bounding box for this cell
        cell_left   = col * col_w
        cell_bottom = grid_top - (row + 1) * row_h
        cell_width  = col_w
        cell_height = row_h

        # Zone axes (inset from cell edges for spacing)
        pad = 0.015
        ax_left   = cell_left   + pad
        ax_bottom = cell_bottom + cell_height * (1 - zone_frac) + pad
        ax_width  = cell_width  - pad * 2
        ax_height = cell_height * zone_frac - pad * 2

        ax = fig.add_axes([ax_left, ax_bottom, ax_width, ax_height])
        ax.set_facecolor(COLORS["bg"])
        axes.append(ax)

        # Batting-team colour accent (top strip of zone ax)
        batting_team = ch.get("away_team") if ch.get("half_inning") == "top" \
                       else ch.get("home_team")
        tc = _team_color(batting_team)
        accent = mpatches.Rectangle(
            (0, 0.94), 1.0, 0.06,
            transform=ax.transAxes,
            color=tc, alpha=0.55, zorder=6,
        )
        ax.add_patch(accent)

        draw_strike_zone(ax, ch)

        # ── Labels below zone ────────────────────────────────────────────────
        outcome   = ch.get("outcome")
        dot_color = OUTCOME_COLORS.get(outcome, COLORS["neutral"])
        label     = OUTCOME_LABELS.get(outcome, "—")
        inning    = ch.get("inning", "?")
        half      = "T" if ch.get("half_inning") == "top" else "B"
        inn_str   = f"{half}{inning}"
        pitcher_s = _last_name(ch.get("pitcher"))
        batter_s  = _last_name(ch.get("batter"))
        edge_d    = ch.get("edge_dist")

        # Count and original call
        cnt       = ch.get("count") or {}
        b_cnt     = cnt.get("balls")
        s_cnt     = cnt.get("strikes")
        count_str = f"{b_cnt}-{s_cnt}" if b_cnt is not None else ""
        orig      = (ch.get("original_call") or "").strip()
        orig_low  = orig.lower()
        if "called strike" in orig_low:
            orig_short = "Called Strike"
        elif "ball" in orig_low:
            orig_short = "Ball"
        else:
            orig_short = orig[:12] if orig else ""

        # Edge distance
        dist_str = ""
        if edge_d is not None:
            d_in = abs(edge_d) * 12
            loc  = "inside zone" if edge_d > 0 else "outside zone"
            dist_str = f"  ·  {d_in:.1f}\" {loc}"

        label_top    = cell_bottom + cell_height * (1 - zone_frac) - pad
        label_center = cell_left + cell_width / 2

        # Row 1: inning · count · original call
        meta_parts = [inn_str]
        if count_str:
            meta_parts.append(count_str)
        if orig_short:
            meta_parts.append(orig_short)
        fig.text(
            label_center,
            label_top - cell_height * label_frac * 0.10,
            "  ·  ".join(meta_parts),
            ha="center", va="top",
            color=COLORS["text_muted"],
            fontsize=6.5,
            transform=fig.transFigure,
        )

        # Row 2: pitcher → batter
        fig.text(
            label_center,
            label_top - cell_height * label_frac * 0.44,
            f"{pitcher_s}  →  {batter_s}",
            ha="center", va="top",
            color=COLORS["text"],
            fontsize=8, fontweight="bold",
            transform=fig.transFigure,
        )

        # Row 3: outcome + edge distance (coloured)
        fig.text(
            label_center,
            label_top - cell_height * label_frac * 0.80,
            f"● {label}{dist_str}",
            ha="center", va="top",
            color=dot_color,
            fontsize=6.5,
            transform=fig.transFigure,
        )

    _set_dark_bg(fig, axes)
    _add_summary_bar(fig, summary, matchup,
                     ump_accuracy=audit_result.get("ump_accuracy", {}))
    _add_legend(fig)

    pk_suffix = f"_{game_pk}" if game_pk else ""
    out_path = OUTPUT_DIR / f"game_card_{game_date.isoformat()}{pk_suffix}.png"
    plt.savefig(out_path, dpi=DPI, bbox_inches="tight", facecolor=COLORS["bg"])
    plt.close(fig)
    log.info("Saved game card → %s", out_path)
    return out_path


# Back-compat alias used by batch/daily mode
def make_daily_card(audit_result: dict, game_date: date,
                    game_pk: int | None = None) -> Path:
    return make_game_card(audit_result, game_date, game_pk=game_pk)


# ── Image 2: Season leaderboard ───────────────────────────────────────────────

def make_leaderboard(leaderboard_df: pd.DataFrame, game_date: date) -> Path | None:
    """
    Season-to-date ABS overturn rate by team (horizontal bar chart).
    leaderboard_df: result of fetch.get_abs_leaderboard(), batter type.
    """
    if leaderboard_df is None or leaderboard_df.empty:
        log.info("Leaderboard data empty — skipping")
        return None

    # Aggregate batter rows to team level
    agg = (
        leaderboard_df
        .groupby("team_abbr", as_index=False)
        .agg(challenges=("n_challenges", "sum"),
             overturns=("n_overturns", "sum"))
    )
    agg = agg[agg["challenges"] > 0].copy()
    agg["rate"] = agg["overturns"] / agg["challenges"] * 100
    agg = agg.sort_values("rate", ascending=True)

    if agg.empty:
        log.info("No team ABS data — skipping leaderboard")
        return None

    teams  = agg["team_abbr"].tolist()
    rates  = agg["rate"].tolist()
    counts = agg["challenges"].tolist()
    n      = len(teams)

    fig_h = max(FH, min(14.0, n * 0.38 + 1.5))
    fig, ax = plt.subplots(figsize=(FW, fig_h), dpi=DPI)
    _set_dark_bg(fig, [ax])

    bar_colors = [TEAM_COLORS.get(t, COLORS["neutral"]) for t in teams]
    bar_h = max(0.35, min(0.72, 8.0 / n))

    bars = ax.barh(teams, rates, color=bar_colors, height=bar_h, zorder=3,
                   alpha=0.85)

    ax.xaxis.grid(True, color=COLORS["border"], linewidth=0.5, zorder=0)
    ax.set_axisbelow(True)

    max_rate = max(rates) if rates else 100
    xlim = max(100, max_rate * 1.22)

    fs_label = max(6, min(9, int(200 / n)))
    for bar, rate, cnt in zip(bars, rates, counts):
        x = bar.get_width() + xlim * 0.015
        ax.text(
            x, bar.get_y() + bar.get_height() / 2,
            f"{rate:.0f}%  ({cnt})",
            va="center", ha="left",
            color=COLORS["text"],
            fontsize=fs_label,
        )

    # League average line
    league_rate = sum(agg["overturns"]) / sum(agg["challenges"]) * 100
    ax.axvline(league_rate, color=COLORS["highlight"], linewidth=1.4,
               linestyle="--", label=f"MLB avg {league_rate:.0f}%", zorder=4)
    ax.legend(facecolor=COLORS["surface"], edgecolor=COLORS["border"],
              labelcolor=COLORS["text"], fontsize=8, loc="lower right")

    ax.set_xlabel("ABS Overturn Rate (%)", color=COLORS["text"], fontsize=10)
    ax.set_title(
        f"ABS CHALLENGE LEADERBOARD — {game_date.strftime('%B %-d, %Y').upper()}",
        color=COLORS["text"], fontsize=13, fontweight="bold", pad=12,
    )
    ax.tick_params(colors=COLORS["text"], labelsize=fs_label)
    ax.yaxis.tick_left()
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    for spine in ("left", "bottom"):
        ax.spines[spine].set_color(COLORS["border"])
    ax.set_xlim(0, xlim)

    fig.text(
        0.50, 0.005,
        "Source: Baseball Savant  |  ABS batter challenges aggregated by team  |  2026 season",
        ha="center", va="bottom",
        color=COLORS["text_muted"], fontsize=7,
        transform=fig.transFigure,
    )

    out_path = OUTPUT_DIR / f"leaderboard_{game_date.isoformat()}.png"
    plt.savefig(out_path, dpi=DPI, bbox_inches="tight", facecolor=COLORS["bg"])
    plt.close(fig)
    log.info("Saved leaderboard → %s", out_path)
    return out_path


# ── Entry point ───────────────────────────────────────────────────────────────

def generate_images(audit_result: dict, season_stats: dict,
                    game_date: date,
                    leaderboard_df: "pd.DataFrame | None" = None,
                    force_leaderboard: bool = False,
                    game_pk: int | None = None,
                    ) -> dict[str, "Path | None"]:
    """
    Generate all images for one game (or a full day in batch mode).

    Returns dict with keys 'daily_card' and 'leaderboard' (may be None).
    """
    daily_card  = make_game_card(audit_result, game_date, game_pk=game_pk)
    leaderboard = None
    if (force_leaderboard or game_date.weekday() == 0) and leaderboard_df is not None:
        leaderboard = make_leaderboard(leaderboard_df, game_date)
    return {"daily_card": daily_card, "leaderboard": leaderboard}
