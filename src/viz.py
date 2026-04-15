"""
ABS Auditor — visualization.

Generates two images:
  Image 1: Daily ABS challenge audit card  (every day)
  Image 2: Season challenge leaderboard    (Mondays only)

Output: PNG files in output/ directory.
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")   # headless
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import matplotlib.patheffects as pe
import numpy as np

import pandas as pd

from src.audit import (
    CORRECT_OVERTURN,
    CORRECT_UPHELD,
    INCORRECT_OVERTURN,
    MISSED_CALL,
)
from src.config import (
    ACCOUNT_HANDLE,
    COLORS,
    DPI,
    FIGURE_HEIGHT_PX,
    FIGURE_WIDTH_PX,
    FOCUS_TEAM,
    MAX_CHALLENGES_ON_CARD,
    OUTPUT_DIR,
    TEAM_COLORS,
    ZONE_HALF_WIDTH_FT,
)

log = logging.getLogger(__name__)

# Derived figure size in inches
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
    INCORRECT_OVERTURN: "Incorrect Overturn",
    CORRECT_UPHELD:     "Upheld ✓",
    MISSED_CALL:        "Missed Call",
    None:               "Unknown",
}


def _hex_to_rgb(h: str) -> tuple[float, float, float]:
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) / 255.0 for i in (0, 2, 4))


def _set_dark_bg(fig: plt.Figure, axes: list) -> None:
    bg = COLORS["bg"]
    fig.patch.set_facecolor(bg)
    for ax in axes:
        ax.set_facecolor(bg)


def _watermark(fig: plt.Figure) -> None:
    fig.text(
        0.985, 0.015, ACCOUNT_HANDLE,
        ha="right", va="bottom",
        color=COLORS["text_muted"],
        fontsize=7,
        alpha=0.6,
        transform=fig.transFigure,
    )


# ── Image 1: Daily audit card ─────────────────────────────────────────────────

def draw_strike_zone(ax: plt.Axes, challenge: dict) -> None:
    """
    Draw a mini strike zone panel and plot the pitch location.
    """
    sz_top = challenge.get("sz_top") or 3.5
    sz_bot = challenge.get("sz_bot") or 1.5
    px     = challenge.get("pitch_x")
    pz     = challenge.get("pitch_z")
    outcome = challenge.get("outcome")

    zone_color = COLORS["zone_fill"]
    edge_color = COLORS["zone_edge"]

    # Zone box
    zone = mpatches.FancyBboxPatch(
        (-ZONE_HALF_WIDTH_FT, sz_bot),
        ZONE_HALF_WIDTH_FT * 2, sz_top - sz_bot,
        boxstyle="square,pad=0",
        linewidth=1.2,
        edgecolor=edge_color,
        facecolor=zone_color,
    )
    ax.add_patch(zone)

    # Pitch dot
    if px is not None and pz is not None:
        dot_color = OUTCOME_COLORS.get(outcome, COLORS["neutral"])
        ax.scatter([px], [pz], s=70, color=dot_color, zorder=5,
                   linewidths=0.8, edgecolors="white")

    # Axis limits with padding
    pad_x = 0.4
    pad_z = 0.5
    ax.set_xlim(-ZONE_HALF_WIDTH_FT - pad_x, ZONE_HALF_WIDTH_FT + pad_x)
    ax.set_ylim(sz_bot - pad_z, sz_top + pad_z)
    ax.set_aspect("equal")
    ax.axis("off")


def make_daily_card(audit_result: dict, game_date: date) -> Path:
    """Generate Image 1 and save to output/. Returns the file path."""
    abs_challs = audit_result["abs_challenges"]
    summary    = audit_result["summary"]
    focus_abs  = audit_result["focus_abs"]

    # Cap at MAX_CHALLENGES_ON_CARD
    display_challs = abs_challs[:MAX_CHALLENGES_ON_CARD]
    n = len(display_challs)

    fig = plt.figure(figsize=(FW, FH), dpi=DPI)
    _set_dark_bg(fig, [])
    fig.patch.set_facecolor(COLORS["bg"])

    # ── Title ──────────────────────────────────────────────────────────────
    date_str = game_date.strftime("%B %-d, %Y").upper()
    fig.text(
        0.5, 0.93,
        f"ABS CHALLENGE AUDIT — {date_str}",
        ha="center", va="top",
        color=COLORS["text"],
        fontsize=16, fontweight="bold",
        transform=fig.transFigure,
    )

    if n == 0:
        # No ABS challenges — show manager challenge summary instead if available
        mgr_count   = len(audit_result.get("manager_challenges", []))
        mgr_over    = sum(1 for c in audit_result.get("manager_challenges", [])
                          if c.get("outcome") == CORRECT_OVERTURN)
        if mgr_count > 0:
            body = (
                f"No ABS challenges yesterday.\n\n"
                f"Manager replay challenges: {mgr_over}/{mgr_count} overturned"
            )
        else:
            body = "No challenges yesterday — clean game."

        fig.text(
            0.5, 0.50, body,
            ha="center", va="center",
            color=COLORS["text_muted"],
            fontsize=16, fontstyle="italic",
            transform=fig.transFigure,
            multialignment="center",
        )
        _watermark(fig)
        _add_summary_bar(fig, summary, season_totals=None)
        out_path = OUTPUT_DIR / f"daily_card_{game_date.isoformat()}.png"
        plt.savefig(out_path, dpi=DPI, bbox_inches="tight",
                    facecolor=COLORS["bg"])
        plt.close(fig)
        log.info("Saved daily card → %s", out_path)
        return out_path

    # ── Grid layout for strike zone panels ────────────────────────────────
    cols = min(n, 3)
    rows = (n + cols - 1) // cols

    # Reserve bottom 18% for summary bar
    grid_top    = 0.86
    grid_bottom = 0.22
    grid_height = grid_top - grid_bottom
    row_h       = grid_height / rows
    col_w       = 1.0 / cols

    # Zone panel occupies the top half of each cell; label below
    zone_frac   = 0.55
    label_frac  = 0.35

    axes: list[plt.Axes] = []
    for idx, ch in enumerate(display_challs):
        row = idx // cols
        col = idx %  cols

        left   = col * col_w + 0.02
        bottom = grid_top - (row + 1) * row_h + (1 - zone_frac) * row_h
        width  = col_w - 0.04
        height = row_h * zone_frac

        ax = fig.add_axes([left, bottom, width, height])
        ax.set_facecolor(COLORS["bg"])
        axes.append(ax)

        # Focus team highlight border
        is_focus = (ch.get("home_team") == FOCUS_TEAM or
                    ch.get("away_team") == FOCUS_TEAM)
        if is_focus:
            rect = mpatches.FancyBboxPatch(
                (0, 0), 1, 1,
                boxstyle="square,pad=0.02",
                linewidth=2,
                edgecolor=COLORS["highlight"],
                facecolor="none",
                transform=ax.transAxes,
                zorder=10,
            )
            ax.add_patch(rect)

        draw_strike_zone(ax, ch)

        # ── Label below zone ───────────────────────────────────────────
        outcome   = ch.get("outcome")
        dot_color = OUTCOME_COLORS.get(outcome, COLORS["neutral"])
        pitcher   = ch.get("pitcher", "?")
        batter    = ch.get("batter", "?")
        label     = OUTCOME_LABELS.get(outcome, "")
        inning    = ch.get("inning", "?")
        half      = "T" if ch.get("half_inning") == "top" else "B"
        inn_str   = f"{half}{inning}"

        label_bottom = bottom - row_h * label_frac
        fig.text(
            left + width / 2,
            label_bottom + row_h * label_frac * 0.7,
            f"{pitcher[:15]}  →  {batter[:15]}",
            ha="center", va="center",
            color=COLORS["text"],
            fontsize=7.5,
            transform=fig.transFigure,
        )
        fig.text(
            left + width / 2,
            label_bottom + row_h * label_frac * 0.3,
            f"{inn_str}  |  ",
            ha="center", va="center",
            color=COLORS["text_muted"],
            fontsize=7,
            transform=fig.transFigure,
        )
        # Coloured outcome dot + label
        fig.text(
            left + width / 2 + 0.025,
            label_bottom + row_h * label_frac * 0.3,
            f"● {label}",
            ha="center", va="center",
            color=dot_color,
            fontsize=7,
            transform=fig.transFigure,
        )

    _set_dark_bg(fig, axes)
    _add_summary_bar(fig, summary, season_totals=None)
    _add_legend(fig)
    _watermark(fig)

    out_path = OUTPUT_DIR / f"daily_card_{game_date.isoformat()}.png"
    plt.savefig(out_path, dpi=DPI, bbox_inches="tight",
                facecolor=COLORS["bg"])
    plt.close(fig)
    log.info("Saved daily card → %s", out_path)
    return out_path


def _add_summary_bar(fig: plt.Figure, summary: dict,
                     season_totals: dict | None) -> None:
    total    = summary.get("total_challenges", 0)
    overturn = summary.get("overturned", 0)
    missed   = summary.get("missed_calls", 0)

    line = (
        f"Yesterday: {overturn} of {total} challenges successful  |  "
        f"{missed} missed call(s) remain"
    )
    fig.text(
        0.5, 0.10, line,
        ha="center", va="center",
        color=COLORS["text"],
        fontsize=9,
        transform=fig.transFigure,
    )
    fig.text(
        0.5, 0.05,
        "Data: MLB Stats API + Baseball Savant",
        ha="center", va="center",
        color=COLORS["text_muted"],
        fontsize=7,
        transform=fig.transFigure,
    )


def _add_legend(fig: plt.Figure) -> None:
    items = [
        (COLORS["correct"], "Correct Overturn"),
        (COLORS["missed"],  "Missed Call / Wrong Overturn"),
        (COLORS["neutral"], "Correctly Upheld"),
    ]
    x = 0.10
    for color, label in items:
        fig.text(x, 0.16, "●", color=color, fontsize=10,
                 transform=fig.transFigure, va="center")
        fig.text(x + 0.025, 0.16, label, color=COLORS["text_muted"],
                 fontsize=7.5, transform=fig.transFigure, va="center")
        x += 0.25


# ── Image 2: Season leaderboard ───────────────────────────────────────────────

def make_leaderboard(leaderboard_df: pd.DataFrame, game_date: date) -> Path | None:
    """
    Generate Image 2: season-to-date ABS challenge success rate by team.

    leaderboard_df: result of fetch.get_abs_leaderboard(), batter type.
    Aggregates to team level so every team appears once.
    Only intended to be posted on Mondays but callable any time.
    """
    if leaderboard_df is None or leaderboard_df.empty:
        log.info("Leaderboard data empty — skipping")
        return None

    # Aggregate batter leaderboard to team level
    agg = (
        leaderboard_df
        .groupby("team_abbr", as_index=False)
        .agg(challenges=("n_challenges", "sum"),
             overturns=("n_overturns", "sum"))
    )
    agg = agg[agg["challenges"] > 0].copy()
    agg["rate"] = agg["overturns"] / agg["challenges"] * 100
    agg = agg.sort_values("rate", ascending=True)   # ascending → focus team pops at top

    if agg.empty:
        log.info("No team ABS data to chart")
        return None

    teams  = agg["team_abbr"].tolist()
    rates  = agg["rate"].tolist()
    counts = agg["challenges"].tolist()
    n      = len(teams)

    # Dynamic figure height: ~0.35 in per team, min 6.75 in (=FH), max 14 in
    fig_h  = max(FH, min(14.0, n * 0.38 + 1.5))
    fig, ax = plt.subplots(figsize=(FW, fig_h), dpi=DPI)
    _set_dark_bg(fig, [ax])

    bar_colors = [
        TEAM_COLORS.get(t, COLORS["yankees_navy"]) if t == FOCUS_TEAM
        else COLORS["neutral"]
        for t in teams
    ]
    bar_h = max(0.35, min(0.72, 8.0 / n))

    bars = ax.barh(teams, rates, color=bar_colors, height=bar_h, zorder=3)

    # Gridlines behind bars
    ax.xaxis.grid(True, color=COLORS["border"], linewidth=0.5, zorder=0)
    ax.set_axisbelow(True)

    max_rate = max(rates) if rates else 100
    xlim = max(100, max_rate * 1.22)

    # Value labels
    fs_label = max(6, min(9, int(200 / n)))
    for bar, rate, cnt in zip(bars, rates, counts):
        x = bar.get_width() + xlim * 0.015
        ax.text(
            x,
            bar.get_y() + bar.get_height() / 2,
            f"{rate:.0f}%  ({cnt}ch)",
            va="center", ha="left",
            color=COLORS["text"],
            fontsize=fs_label,
        )

    # League-average line
    league_rate = sum(agg["overturns"]) / sum(agg["challenges"]) * 100
    ax.axvline(league_rate, color=COLORS["highlight"], linewidth=1.2,
               linestyle="--", label=f"Avg {league_rate:.0f}%", zorder=4)
    ax.legend(facecolor=COLORS["surface"], edgecolor=COLORS["border"],
              labelcolor=COLORS["text"], fontsize=8, loc="lower right")

    ax.set_xlabel("Overturn Rate (%)", color=COLORS["text"], fontsize=10)
    ax.set_title(
        f"ABS CHALLENGE LEADERBOARD — {game_date.strftime('%B %-d, %Y').upper()}",
        color=COLORS["text"],
        fontsize=13,
        fontweight="bold",
        pad=10,
    )
    ax.tick_params(colors=COLORS["text"], labelsize=fs_label)
    ax.yaxis.tick_left()
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    for spine in ("left", "bottom"):
        ax.spines[spine].set_color(COLORS["border"])
    ax.set_xlim(0, xlim)

    fig.text(
        0.5, 0.005,
        "Data: Baseball Savant  |  ABS batter challenges aggregated by team",
        ha="center", va="bottom",
        color=COLORS["text_muted"],
        fontsize=7,
        transform=fig.transFigure,
    )
    _watermark(fig)

    out_path = OUTPUT_DIR / f"leaderboard_{game_date.isoformat()}.png"
    plt.savefig(out_path, dpi=DPI, bbox_inches="tight",
                facecolor=COLORS["bg"])
    plt.close(fig)
    log.info("Saved leaderboard → %s", out_path)
    return out_path


# ── Entry point ───────────────────────────────────────────────────────────────

def generate_images(audit_result: dict, season_stats: dict,
                    game_date: date,
                    leaderboard_df: "pd.DataFrame | None" = None,
                    force_leaderboard: bool = False,
                    ) -> dict[str, "Path | None"]:
    """
    Generate all images for a given day.

    leaderboard_df: pre-fetched Savant ABS leaderboard DataFrame.
    Returns a dict with keys 'daily_card' and 'leaderboard' (may be None).
    """
    daily_card  = make_daily_card(audit_result, game_date)
    leaderboard = None
    post_lb = force_leaderboard or game_date.weekday() == 0   # always on Mondays
    if post_lb and leaderboard_df is not None:
        leaderboard = make_leaderboard(leaderboard_df, game_date)

    return {"daily_card": daily_card, "leaderboard": leaderboard}
