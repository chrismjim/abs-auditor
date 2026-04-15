"""
ABS Auditor — visualization (v3).

Per-game card layout:
  LEFT  (58%): Unified strike zone — every wrong strike + wrong ball plotted,
               ABS challenges overlaid as larger labelled dots.
  RIGHT (42%): Stats panel — ump accuracy, ABS challenge list.
  FOOTER:      Legend + data source.
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
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
    OUTPUT_DIR,
    TEAM_COLORS,
    ZONE_HALF_WIDTH_FT,
)

log = logging.getLogger(__name__)

FW = FIGURE_WIDTH_PX / DPI
FH = FIGURE_HEIGHT_PX / DPI

# Zone display bounds (ft from centre of plate) — tight crop around zone
_ZX     = 1.35   # ± horizontal limit (clips <1% of edge outliers)
_ZZ_BOT = 0.9
_ZZ_TOP = 4.4

# Standard zone for the background box (average MLB batter)
_SZ_TOP = 3.5
_SZ_BOT = 1.5

OUTCOME_COLORS = {
    CORRECT_OVERTURN:   COLORS["correct"],
    INCORRECT_OVERTURN: COLORS["highlight"],
    CORRECT_UPHELD:     COLORS["neutral"],
    MISSED_CALL:        COLORS["missed"],
    None:               COLORS["neutral"],
}

OUTCOME_SHORT = {
    CORRECT_OVERTURN:   "Overturned",
    INCORRECT_OVERTURN: "Wrong OT",
    CORRECT_UPHELD:     "Upheld",
    MISSED_CALL:        "Missed",
    None:               "—",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _set_dark_bg(fig: plt.Figure, axes: list) -> None:
    fig.patch.set_facecolor(COLORS["bg"])
    for ax in axes:
        ax.set_facecolor(COLORS["bg"])


def _last_name(full: str | None) -> str:
    if not full:
        return "?"
    parts = full.split()
    return parts[-1] if len(parts) > 1 else full


def _team_color(abbr: str | None) -> str:
    return TEAM_COLORS.get(abbr or "", COLORS["border"])


def _parse_matchup(matchup: str | None) -> tuple[str, str]:
    if matchup and " @ " in matchup:
        away, _, home = matchup.partition(" @ ")
        return away.strip(), home.strip()
    return "", ""


# ── Header ────────────────────────────────────────────────────────────────────

def _draw_header(fig: plt.Figure, audit_result: dict, game_date: date) -> float:
    matchup  = audit_result.get("matchup", "")
    date_str = game_date.strftime("%B %-d, %Y").upper()
    away, home = _parse_matchup(matchup)
    score    = audit_result.get("final_score", {}) or {}
    away_sc  = score.get("away")
    home_sc  = score.get("home")

    if away and home:
        away_c = _team_color(away)
        home_c = _team_color(home)

        for x0, colour in [(0.0, away_c), (0.5, home_c)]:
            fig.add_artist(mpatches.Rectangle(
                (x0, 0.892), 0.5, 0.009,
                transform=fig.transFigure,
                color=colour, alpha=0.9, zorder=4,
            ))

        # Away abbreviation
        fig.text(0.22, 0.950, away, ha="center", va="center",
                 color=away_c, fontsize=26, fontweight="bold",
                 transform=fig.transFigure)

        # Score (if available)
        if away_sc is not None and home_sc is not None:
            score_str = f"{away_sc}  –  {home_sc}"
            fig.text(0.50, 0.951, score_str, ha="center", va="center",
                     color=COLORS["text"], fontsize=20, fontweight="bold",
                     transform=fig.transFigure)
        else:
            fig.text(0.50, 0.948, "@", ha="center", va="center",
                     color=COLORS["text_muted"], fontsize=18,
                     transform=fig.transFigure)

        # Home abbreviation
        fig.text(0.78, 0.950, home, ha="center", va="center",
                 color=home_c, fontsize=26, fontweight="bold",
                 transform=fig.transFigure)

        fig.text(0.50, 0.905,
                 f"ABS CHALLENGE AUDIT  ·  {date_str}",
                 ha="center", va="center",
                 color=COLORS["text_muted"], fontsize=9.5,
                 transform=fig.transFigure)
        content_top = 0.885

    else:
        fig.text(0.50, 0.950, "MLB ABS CHALLENGE AUDIT",
                 ha="center", va="center",
                 color=COLORS["text"], fontsize=16, fontweight="bold",
                 transform=fig.transFigure)
        fig.text(0.50, 0.910, date_str, ha="center", va="center",
                 color=COLORS["text_muted"], fontsize=10,
                 transform=fig.transFigure)
        content_top = 0.890

    return content_top


# ── Unified zone diagram ──────────────────────────────────────────────────────

def _draw_unified_zone(ax: plt.Axes, abs_challenges: list[dict],
                       ump_accuracy: dict) -> None:
    """
    Single strike-zone axes showing:
      • Small red ×  — every wrong strike (CS outside zone)
      • Small yellow +  — every wrong ball (ball inside zone)
      • Large coloured ●  — each ABS challenge (outcome colour)
    """
    ua = ump_accuracy or {}

    ax.set_facecolor(COLORS["bg"])
    ax.set_xlim(-_ZX, _ZX)
    ax.set_ylim(_ZZ_BOT, _ZZ_TOP)
    ax.axis("off")

    # ── Background: plate shadow ─────────────────────────────────────────────
    plate_w = 17 / 12   # 17 inches = 1.4167 ft
    plate_h = 0.15
    ax.add_patch(mpatches.FancyBboxPatch(
        (-plate_w / 2, _SZ_BOT - plate_h - 0.05), plate_w, plate_h,
        boxstyle="square,pad=0",
        linewidth=0, facecolor="#222b38", zorder=1,
    ))

    # ── Strike zone box ──────────────────────────────────────────────────────
    ax.add_patch(mpatches.FancyBboxPatch(
        (-ZONE_HALF_WIDTH_FT, _SZ_BOT),
        ZONE_HALF_WIDTH_FT * 2, _SZ_TOP - _SZ_BOT,
        boxstyle="square,pad=0",
        linewidth=1.6, edgecolor=COLORS["zone_edge"],
        facecolor=COLORS["zone_fill"], zorder=2,
    ))

    # Inner quadrant lines
    mid_z = (_SZ_TOP + _SZ_BOT) / 2
    for xs, xe, ys, ye in [
        (-ZONE_HALF_WIDTH_FT, ZONE_HALF_WIDTH_FT, mid_z, mid_z),
        (0, 0, _SZ_BOT, _SZ_TOP),
    ]:
        ax.plot([xs, xe], [ys, ye], color=COLORS["border"],
                linewidth=0.5, zorder=2)

    # ── Wrong strikes (small red ×) ──────────────────────────────────────────
    ws_coords = ua.get("wrong_strike_coords", [])
    if ws_coords:
        xs, zs = zip(*ws_coords)
        ax.scatter(xs, zs, marker="x", s=55, color=COLORS["missed"],
                   linewidths=1.4, alpha=0.75, zorder=3,
                   label=f"Wrong strike ({len(ws_coords)})")

    # ── Wrong balls (small yellow +) ─────────────────────────────────────────
    wb_coords = ua.get("wrong_ball_coords", [])
    if wb_coords:
        xb, zb = zip(*wb_coords)
        ax.scatter(xb, zb, marker="+", s=55, color=COLORS["highlight"],
                   linewidths=1.4, alpha=0.75, zorder=3,
                   label=f"Wrong ball ({len(wb_coords)})")

    # ── ABS challenges (large coloured dots with inning label) ───────────────
    for ch in abs_challenges:
        px = ch.get("pitch_x")
        pz = ch.get("pitch_z")
        if px is None or pz is None:
            continue

        outcome   = ch.get("outcome")
        dot_color = OUTCOME_COLORS.get(outcome, COLORS["neutral"])
        half      = "T" if ch.get("half_inning") == "top" else "B"
        inn       = ch.get("inning", "?")
        cnt       = ch.get("count") or {}
        b, s      = cnt.get("balls"), cnt.get("strikes")
        cnt_str   = f"{b}-{s}" if b is not None else ""

        # Large dot
        ax.scatter([px], [pz], s=160, color=dot_color,
                   linewidths=1.2, edgecolors="white", zorder=5)

        # Inning label above dot
        label = f"{half}{inn}" + (f"\n{cnt_str}" if cnt_str else "")
        ax.annotate(
            label,
            xy=(px, pz),
            xytext=(0, 11),
            textcoords="offset points",
            ha="center", va="bottom",
            color=dot_color,
            fontsize=5.5, fontweight="bold",
            zorder=6,
        )

    # ── Zone label ───────────────────────────────────────────────────────────
    ax.text(0, _SZ_BOT - 0.12, "STRIKE ZONE",
            ha="center", va="top",
            color=COLORS["text_muted"], fontsize=6, alpha=0.7)


# ── Right stats panel ─────────────────────────────────────────────────────────

def _draw_stats_panel(fig: plt.Figure, audit_result: dict,
                      content_top: float) -> None:
    """
    Text panel occupying the right 40% of the card.
    Shows ump accuracy breakdown + ABS challenge list.
    """
    ua       = audit_result.get("ump_accuracy", {}) or {}
    abs_ch   = audit_result.get("abs_challenges", [])
    mgr_ch   = audit_result.get("manager_challenges", [])
    summary  = audit_result.get("summary", {})

    x_left  = 0.700   # figure fraction
    y_start = content_top - 0.02
    line_h  = 0.068   # vertical step per line
    y       = y_start

    def _txt(text, x=x_left, dy=0, size=8.5, color=COLORS["text"],
             weight="normal", alpha=1.0):
        nonlocal y
        fig.text(x + 0.005, y + dy, text,
                 ha="left", va="top",
                 color=color, fontsize=size, fontweight=weight,
                 alpha=alpha, transform=fig.transFigure)

    def _step(n=1):
        nonlocal y
        y -= line_h * n

    # ── Divider ──────────────────────────────────────────────────────────────
    fig.add_artist(mpatches.Rectangle(
        (x_left - 0.014, 0.17), 0.002, content_top - 0.19,
        transform=fig.transFigure,
        color=COLORS["border"], zorder=3,
    ))

    # ── Umpire section ───────────────────────────────────────────────────────
    ump_name = ua.get("name")
    ump_tot  = ua.get("total_called", 0)
    ump_cor  = ua.get("correct", 0)
    ump_pct  = ua.get("accuracy_pct")
    ws       = ua.get("wrong_strikes", 0)
    wb       = ua.get("wrong_balls", 0)

    _txt("HP UMPIRE", size=7, color=COLORS["text_muted"], weight="bold")
    _step(0.6)

    if ump_name:
        _txt(ump_name, size=11, weight="bold")
        _step(0.85)

    if ump_tot >= 5 and ump_pct is not None:
        pct_color = COLORS["correct"] if ump_pct >= 95 else \
                    COLORS["highlight"] if ump_pct >= 88 else COLORS["missed"]
        _txt(f"{ump_pct:.0f}%  accurate", size=14, color=pct_color, weight="bold")
        _step(0.75)
        _txt(f"{ump_cor} / {ump_tot} called pitches correct",
             size=7.5, color=COLORS["text_muted"])
        _step(0.75)

    if ws:
        _txt(f"✕  {ws} wrong strike{'s' if ws != 1 else ''}",
             size=8, color=COLORS["missed"])
        _step(0.75)
    if wb:
        _txt(f"+  {wb} wrong ball{'s' if wb != 1 else ''}",
             size=8, color=COLORS["highlight"])
        _step(0.75)

    # Spacer
    _step(0.4)

    # ── ABS Challenges section ───────────────────────────────────────────────
    if abs_ch:
        _txt("ABS CHALLENGES", size=7, color=COLORS["text_muted"], weight="bold")
        _step(0.65)

        for ch in abs_ch:
            outcome   = ch.get("outcome")
            dot_color = OUTCOME_COLORS.get(outcome, COLORS["neutral"])
            short     = OUTCOME_SHORT.get(outcome, "—")
            half      = "T" if ch.get("half_inning") == "top" else "B"
            inn       = ch.get("inning", "?")
            pitcher   = _last_name(ch.get("pitcher"))
            batter    = _last_name(ch.get("batter"))
            cnt       = ch.get("count") or {}
            b, s      = cnt.get("balls"), cnt.get("strikes")
            cnt_str   = f" {b}-{s}" if b is not None else ""
            edge_d    = ch.get("edge_dist")
            orig      = (ch.get("original_call") or "").lower()
            call_w    = "CS" if "called strike" in orig else "Ball"

            dist_str = ""
            if edge_d is not None:
                d_in = abs(edge_d) * 12
                loc  = "in" if edge_d > 0 else "out"
                dist_str = f"  {d_in:.1f}\"{loc}"

            # Coloured dot marker + challenge line
            fig.text(x_left + 0.005, y, "●",
                     ha="left", va="top",
                     color=dot_color, fontsize=9,
                     transform=fig.transFigure)
            fig.text(x_left + 0.023, y,
                     f"{half}{inn}{cnt_str}  {pitcher}→{batter}",
                     ha="left", va="top",
                     color=COLORS["text"], fontsize=8, fontweight="bold",
                     transform=fig.transFigure)
            _step(0.60)
            _txt(f"   {call_w}  ·  {short}{dist_str}",
                 size=7, color=dot_color)
            _step(0.75)

    elif summary.get("no_challenges"):
        _txt("ABS CHALLENGES", size=7, color=COLORS["text_muted"], weight="bold")
        _step(0.65)
        _txt("None this game ✓", size=8.5, color=COLORS["correct"])
        _step(0.75)

    # ── Manager challenges (brief) ───────────────────────────────────────────
    if mgr_ch:
        _step(0.3)
        mgr_over = sum(1 for c in mgr_ch if c.get("outcome") == CORRECT_OVERTURN)
        _txt("REPLAY CHALLENGES", size=7, color=COLORS["text_muted"], weight="bold")
        _step(0.65)
        _txt(f"{len(mgr_ch)} total  ·  {mgr_over} overturned",
             size=8, color=COLORS["text"])
        _step(0.75)


# ── Footer ────────────────────────────────────────────────────────────────────

def _add_footer(fig: plt.Figure, ump_accuracy: dict | None = None) -> None:
    ua = ump_accuracy or {}

    # Legend row
    legend_items = [
        (COLORS["missed"],    "×",  "Wrong Strike"),
        (COLORS["highlight"], "+",  "Wrong Ball"),
        (COLORS["correct"],   "●",  "ABS: Overturned"),
        (COLORS["missed"],    "●",  "ABS: Missed"),
        (COLORS["neutral"],   "●",  "ABS: Upheld"),
    ]
    n     = len(legend_items)
    total_w = 0.88
    start_x = (1.0 - total_w) / 2
    step    = total_w / n

    for i, (color, marker, label) in enumerate(legend_items):
        x = start_x + i * step + step / 2
        fig.text(x - 0.02, 0.155, marker,
                 color=color, fontsize=9 if marker == "●" else 8,
                 ha="right", va="center",
                 transform=fig.transFigure)
        fig.text(x - 0.015, 0.155, label,
                 color=COLORS["text_muted"], fontsize=6.5,
                 ha="left", va="center",
                 transform=fig.transFigure)

    # Data source
    fig.text(0.50, 0.045,
             "Data: MLB Stats API  +  Baseball Savant / Statcast",
             ha="center", va="center",
             color=COLORS["text_muted"], fontsize=6.5,
             transform=fig.transFigure)


# ── Image 1: per-game audit card ──────────────────────────────────────────────

def make_game_card(audit_result: dict, game_date: date,
                   game_pk: int | None = None) -> Path:
    abs_challs = audit_result.get("abs_challenges", [])
    ua         = audit_result.get("ump_accuracy", {}) or {}

    fig = plt.figure(figsize=(FW, FH), dpi=DPI)
    _set_dark_bg(fig, [])

    content_top = _draw_header(fig, audit_result, game_date)

    # ── Left: unified zone axes (70% of figure width) ───────────────────────
    grid_bot = 0.18
    ax_h     = content_top - 0.005 - grid_bot
    ax = fig.add_axes([0.02, grid_bot, 0.66, ax_h])
    _set_dark_bg(fig, [ax])
    _draw_unified_zone(ax, abs_challs, ua)

    # ── Right: stats panel ───────────────────────────────────────────────────
    _draw_stats_panel(fig, audit_result, content_top)

    # ── Footer ───────────────────────────────────────────────────────────────
    _add_footer(fig, ua)

    pk_suffix = f"_{game_pk}" if game_pk else ""
    out_path  = OUTPUT_DIR / f"game_card_{game_date.isoformat()}{pk_suffix}.png"
    plt.savefig(out_path, dpi=DPI, bbox_inches="tight", facecolor=COLORS["bg"])
    plt.close(fig)
    log.info("Saved game card → %s", out_path)
    return out_path


# Back-compat alias
def make_daily_card(audit_result: dict, game_date: date,
                    game_pk: int | None = None) -> Path:
    return make_game_card(audit_result, game_date, game_pk=game_pk)


# ── Image 2: Season leaderboard ───────────────────────────────────────────────

def make_leaderboard(leaderboard_df: pd.DataFrame, game_date: date) -> Path | None:
    if leaderboard_df is None or leaderboard_df.empty:
        log.info("Leaderboard data empty — skipping")
        return None

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
    bars  = ax.barh(teams, rates, color=bar_colors, height=bar_h,
                    zorder=3, alpha=0.85)

    ax.xaxis.grid(True, color=COLORS["border"], linewidth=0.5, zorder=0)
    ax.set_axisbelow(True)
    max_rate = max(rates) if rates else 100
    xlim     = max(100, max_rate * 1.22)
    fs_label = max(6, min(9, int(200 / n)))

    for bar, rate, cnt in zip(bars, rates, counts):
        ax.text(bar.get_width() + xlim * 0.015,
                bar.get_y() + bar.get_height() / 2,
                f"{rate:.0f}%  ({cnt})",
                va="center", ha="left",
                color=COLORS["text"], fontsize=fs_label)

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

    fig.text(0.50, 0.005,
             "Source: Baseball Savant  |  ABS batter challenges  |  2026 season",
             ha="center", va="bottom",
             color=COLORS["text_muted"], fontsize=7,
             transform=fig.transFigure)

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
    daily_card  = make_game_card(audit_result, game_date, game_pk=game_pk)
    leaderboard = None
    if (force_leaderboard or game_date.weekday() == 0) and leaderboard_df is not None:
        leaderboard = make_leaderboard(leaderboard_df, game_date)
    return {"daily_card": daily_card, "leaderboard": leaderboard}
