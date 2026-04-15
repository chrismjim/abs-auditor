"""
ABS Auditor — visualization (v4).

Inspired by @UmpScorecards: clean dark-mode card with a prominent,
correctly-proportioned strike zone showing every wrong call overlaid
with ABS challenge results.

Layout (1200 × 675 px):
  Header  : full-width, 14 % height — teams, score, date
  Zone    : left 45 %, portrait axes, equal-aspect → correct zone box
  Stats   : right 48 %, clean typographic hierarchy
  Legend  : full-width footer strip
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.patches as mpatches
import matplotlib.patheffects as pe
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D

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

FW = FIGURE_WIDTH_PX / DPI   # 12.0 in
FH = FIGURE_HEIGHT_PX / DPI  # 6.75 in

# ── Zone display parameters ───────────────────────────────────────────────────
# Tight crop: just enough margin to show pitches just off the zone.
# Equal aspect + these bounds give the zone box the correct 17" × ~24" shape.
_DX      = 1.25   # ± ft shown on X axis
_DZ_BOT  = 1.20   # ft — bottom of display
_DZ_TOP  = 3.95   # ft — top of display

# Standard MLB average zone used for the drawn box
_SZ_TOP  = 3.50
_SZ_BOT  = 1.50

# Outcome colours / labels
OUTCOME_COLOR = {
    CORRECT_OVERTURN:   "#3fb950",   # green
    INCORRECT_OVERTURN: "#e3b341",   # amber
    CORRECT_UPHELD:     "#848d97",   # grey
    MISSED_CALL:        "#f85149",   # red
    None:               "#848d97",
}
OUTCOME_LABEL = {
    CORRECT_OVERTURN:   "Overturned",
    INCORRECT_OVERTURN: "Wrong OT",
    CORRECT_UPHELD:     "Upheld",
    MISSED_CALL:        "Missed",
    None:               "—",
}


# ── Tiny utilities ────────────────────────────────────────────────────────────

def _tc(abbr: str | None) -> str:
    return TEAM_COLORS.get(abbr or "", "#848d97")


def _last(name: str | None) -> str:
    if not name:
        return "?"
    p = name.split()
    return p[-1] if len(p) > 1 else name


def _parse_matchup(m: str | None) -> tuple[str, str]:
    if m and " @ " in m:
        a, _, h = m.partition(" @ ")
        return a.strip(), h.strip()
    return "", ""


# ── Header ────────────────────────────────────────────────────────────────────

def _draw_header(fig: plt.Figure, audit_result: dict, game_date: date) -> None:
    """
    Clean two-row header:
      Row 1: thin team-colour accent bar (very top)
      Row 2: AWAY  score  HOME  (large, team colours)
      Row 3: subtitle — ABS AUDIT · DATE
    No overlapping elements.
    """
    matchup = audit_result.get("matchup", "")
    away, home = _parse_matchup(matchup)
    score   = audit_result.get("final_score", {}) or {}
    a_sc    = score.get("away")
    h_sc    = score.get("home")
    date_str = game_date.strftime("%B %-d, %Y").upper()

    # ── Thin accent bars at very top (not touching text) ─────────────────────
    if away and home:
        for x0, c in [(0.0, _tc(away)), (0.5, _tc(home))]:
            fig.add_artist(mpatches.Rectangle(
                (x0, 0.960), 0.5, 0.040,
                transform=fig.transFigure,
                color=c, alpha=0.90, zorder=5,
            ))

    # ── Team / score row ─────────────────────────────────────────────────────
    if away and home:
        # Away
        fig.text(0.275, 0.895, away,
                 ha="center", va="center",
                 color=_tc(away), fontsize=30, fontweight="bold",
                 transform=fig.transFigure)
        # Score
        if a_sc is not None and h_sc is not None:
            fig.text(0.500, 0.895, f"{a_sc}  –  {h_sc}",
                     ha="center", va="center",
                     color=COLORS["text"], fontsize=24, fontweight="bold",
                     transform=fig.transFigure)
        else:
            fig.text(0.500, 0.895, "vs",
                     ha="center", va="center",
                     color=COLORS["text_muted"], fontsize=18,
                     transform=fig.transFigure)
        # Home
        fig.text(0.725, 0.895, home,
                 ha="center", va="center",
                 color=_tc(home), fontsize=30, fontweight="bold",
                 transform=fig.transFigure)
    else:
        fig.text(0.500, 0.895, "MLB ABS AUDIT",
                 ha="center", va="center",
                 color=COLORS["text"], fontsize=22, fontweight="bold",
                 transform=fig.transFigure)

    # ── Subtitle ─────────────────────────────────────────────────────────────
    fig.text(0.500, 0.840,
             f"ABS CHALLENGE AUDIT  ·  {date_str}",
             ha="center", va="center",
             color=COLORS["text_muted"], fontsize=8.5,
             transform=fig.transFigure)

    # ── Hairline separator ────────────────────────────────────────────────────
    fig.add_artist(mpatches.Rectangle(
        (0.03, 0.818), 0.94, 0.0015,
        transform=fig.transFigure,
        color=COLORS["border"], zorder=3,
    ))


# ── Strike-zone diagram ───────────────────────────────────────────────────────

def _draw_zone(ax: plt.Axes,
               abs_challenges: list[dict],
               ump_accuracy: dict) -> None:
    """
    Catcher's-view strike zone with:
      • Red dots   — every wrong strike (CS outside zone)
      • Gold dots  — every wrong ball   (ball inside zone)
      • Large outlined dot — each ABS challenge (outcome colour)
      • Inning label above each ABS dot
    """
    ua = ump_accuracy or {}

    ax.set_facecolor("#0d1117")
    ax.set_xlim(-_DX, _DX)
    ax.set_ylim(_DZ_BOT, _DZ_TOP)
    ax.set_aspect("equal", adjustable="box")
    ax.axis("off")

    # ── Home plate silhouette ─────────────────────────────────────────────────
    pw = ZONE_HALF_WIDTH_FT           # 0.7083 ft = half plate width
    ph = 0.12
    plate_y = _SZ_BOT - ph - 0.05
    plate = mpatches.FancyBboxPatch(
        (-pw, plate_y), pw * 2, ph,
        boxstyle="round,pad=0.02",
        linewidth=0, facecolor="#1f2937",
    )
    ax.add_patch(plate)
    ax.text(0, plate_y + ph / 2, "HOME PLATE",
            ha="center", va="center",
            color="#4b5563", fontsize=4.5, fontweight="bold")

    # ── Strike zone box ───────────────────────────────────────────────────────
    zone_rect = mpatches.Rectangle(
        (-ZONE_HALF_WIDTH_FT, _SZ_BOT),
        ZONE_HALF_WIDTH_FT * 2, _SZ_TOP - _SZ_BOT,
        linewidth=1.8,
        edgecolor="#444c56",
        facecolor="#161b22",
    )
    ax.add_patch(zone_rect)

    # ── 3 × 3 quadrant grid inside zone ──────────────────────────────────────
    w  = ZONE_HALF_WIDTH_FT
    dz = (_SZ_TOP - _SZ_BOT) / 3
    dx = w * 2 / 3
    for i in (1, 2):
        ax.plot([-w, w],
                [_SZ_BOT + i * dz, _SZ_BOT + i * dz],
                color="#2d333b", linewidth=0.8, zorder=2)
        ax.plot([-w + i * dx, -w + i * dx],
                [_SZ_BOT, _SZ_TOP],
                color="#2d333b", linewidth=0.8, zorder=2)

    # ── Wrong strikes (red circles outside zone) ──────────────────────────────
    ws = ua.get("wrong_strike_coords", [])
    if ws:
        xs, zs = zip(*ws)
        ax.scatter(xs, zs,
                   s=22, color="#f85149", alpha=0.72,
                   linewidths=0, zorder=4)

    # ── Wrong balls (gold circles inside zone) ────────────────────────────────
    wb = ua.get("wrong_ball_coords", [])
    if wb:
        xb, zb = zip(*wb)
        ax.scatter(xb, zb,
                   s=22, color="#e3b341", alpha=0.72,
                   linewidths=0, zorder=4)

    # ── ABS challenge dots ────────────────────────────────────────────────────
    for ch in abs_challenges:
        px = ch.get("pitch_x")
        pz = ch.get("pitch_z")
        if px is None or pz is None:
            continue

        outcome = ch.get("outcome")
        color   = OUTCOME_COLOR.get(outcome, COLORS["neutral"])
        half    = "T" if ch.get("half_inning") == "top" else "B"
        inn     = ch.get("inning", "?")
        cnt     = ch.get("count") or {}
        b, s    = cnt.get("balls"), cnt.get("strikes")
        cnt_str = f"{b}-{s}" if b is not None else ""

        # Large dot with white border
        ax.scatter([px], [pz],
                   s=110, color=color, zorder=6,
                   linewidths=1.5, edgecolors="white")

        # Label: inning on first line, count on second
        label = f"{half}{inn}" + (f"\n{cnt_str}" if cnt_str else "")
        ax.annotate(
            label,
            xy=(px, pz), xytext=(0, 9),
            textcoords="offset points",
            ha="center", va="bottom",
            color=color, fontsize=5.5, fontweight="bold",
            zorder=7,
        )

    # ── "STRIKE ZONE" label ───────────────────────────────────────────────────
    ax.text(0, _DZ_BOT + 0.02, "STRIKE ZONE",
            ha="center", va="bottom",
            color="#3d444d", fontsize=5.5,
            fontweight="bold")


# ── Stats panel ───────────────────────────────────────────────────────────────

def _draw_stats(fig: plt.Figure, audit_result: dict) -> None:
    """Right-side text panel: ump accuracy + challenge list."""

    ua      = audit_result.get("ump_accuracy", {}) or {}
    abs_ch  = audit_result.get("abs_challenges", [])
    mgr_ch  = audit_result.get("manager_challenges", [])
    summary = audit_result.get("summary", {})

    X     = 0.515          # left edge of panel (figure fraction)
    y     = 0.790          # running y cursor (figure fraction)
    LH    = 0.062          # normal line height
    LH_SM = 0.048          # small line height

    def txt(s, dy=0, size=8.5, color=COLORS["text"],
            weight="normal", alpha=1.0, x=X):
        fig.text(x, y + dy, s,
                 ha="left", va="top",
                 color=color, fontsize=size,
                 fontweight=weight, alpha=alpha,
                 transform=fig.transFigure)

    def step(n=1, small=False):
        nonlocal y
        y -= (LH_SM if small else LH) * n

    # ── Vertical divider ─────────────────────────────────────────────────────
    fig.add_artist(mpatches.Rectangle(
        (X - 0.016, 0.085), 0.0014, 0.720,
        transform=fig.transFigure,
        color=COLORS["border"], zorder=3,
    ))

    # ── HP UMPIRE section ─────────────────────────────────────────────────────
    txt("HP UMPIRE", size=7, color=COLORS["text_muted"], weight="bold")
    step(0.55)

    ump_name = ua.get("name", "")
    ump_tot  = ua.get("total_called", 0)
    ump_cor  = ua.get("correct", 0)
    ump_pct  = ua.get("accuracy_pct")
    ws       = ua.get("wrong_strikes", 0)
    wb       = ua.get("wrong_balls", 0)

    if ump_name:
        txt(ump_name, size=13, weight="bold")
        step(0.90)

    if ump_tot >= 5 and ump_pct is not None:
        pct_color = (COLORS["correct"]   if ump_pct >= 95 else
                     COLORS["highlight"] if ump_pct >= 88 else
                     COLORS["missed"])
        txt(f"{ump_pct:.0f}%", size=26, color=pct_color, weight="bold")
        step(0.95)
        txt(f"{ump_cor} / {ump_tot} called pitches correct",
            size=7.5, color=COLORS["text_muted"])
        step(0.80)

    if ws:
        txt(f"● {ws} wrong strike{'s' if ws != 1 else ''}",
            size=8, color=COLORS["missed"])
        step(0.75, small=True)
    if wb:
        txt(f"● {wb} wrong ball{'s' if wb != 1 else ''}",
            size=8, color=COLORS["highlight"])
        step(0.75, small=True)

    step(0.55)   # spacer

    # ── ABS CHALLENGES ────────────────────────────────────────────────────────
    if abs_ch:
        txt("ABS CHALLENGES", size=7, color=COLORS["text_muted"], weight="bold")
        step(0.55)

        for ch in abs_ch:
            outcome = ch.get("outcome")
            color   = OUTCOME_COLOR.get(outcome, COLORS["neutral"])
            label   = OUTCOME_LABEL.get(outcome, "—")
            half    = "T" if ch.get("half_inning") == "top" else "B"
            inn     = ch.get("inning", "?")
            pitcher = _last(ch.get("pitcher"))
            batter  = _last(ch.get("batter"))
            cnt     = ch.get("count") or {}
            b, s    = cnt.get("balls"), cnt.get("strikes")
            cnt_str = f" {b}-{s}" if b is not None else ""
            edge_d  = ch.get("edge_dist")
            orig    = (ch.get("original_call") or "").lower()
            call_lbl = "CS" if "called strike" in orig else "Ball"

            dist = ""
            if edge_d is not None:
                d_in = abs(edge_d) * 12
                loc  = "in" if edge_d > 0 else "out"
                dist = f"  {d_in:.1f}\" {loc}"

            # Coloured dot inline with challenge line
            fig.text(X, y, "●",
                     ha="left", va="top",
                     color=color, fontsize=8.5,
                     transform=fig.transFigure)
            fig.text(X + 0.018, y,
                     f"{half}{inn}{cnt_str}  {pitcher} → {batter}",
                     ha="left", va="top",
                     color=COLORS["text"], fontsize=8, fontweight="bold",
                     transform=fig.transFigure)
            step(0.60, small=True)
            txt(f"    {call_lbl}  ·  {label}{dist}",
                size=7, color=color)
            step(0.90, small=True)

    elif summary.get("no_challenges"):
        txt("ABS CHALLENGES", size=7, color=COLORS["text_muted"], weight="bold")
        step(0.55)
        txt("None this game  ✓", size=9, color=COLORS["correct"])
        step(0.80)

    # ── REPLAY CHALLENGES ─────────────────────────────────────────────────────
    if mgr_ch:
        step(0.30)
        mgr_over = sum(1 for c in mgr_ch if c.get("outcome") == CORRECT_OVERTURN)
        txt("REPLAY CHALLENGES", size=7,
            color=COLORS["text_muted"], weight="bold")
        step(0.55)
        txt(f"{len(mgr_ch)} total  ·  {mgr_over} overturned",
            size=8, color=COLORS["text"])


# ── Legend strip ──────────────────────────────────────────────────────────────

def _draw_legend(fig: plt.Figure) -> None:
    items = [
        ("#f85149", "Wrong Strike"),
        ("#e3b341", "Wrong Ball"),
        ("#3fb950", "ABS: Overturned"),
        ("#f85149", "ABS: Missed"),
        ("#848d97", "ABS: Upheld"),
    ]
    n       = len(items)
    total_w = 0.74
    x0      = (1.0 - total_w) / 2
    step    = total_w / n

    for i, (color, label) in enumerate(items):
        cx = x0 + i * step + step / 2
        fig.text(cx - 0.018, 0.060, "●",
                 ha="right", va="center",
                 color=color, fontsize=9,
                 transform=fig.transFigure)
        fig.text(cx - 0.012, 0.060, label,
                 ha="left", va="center",
                 color=COLORS["text_muted"], fontsize=7,
                 transform=fig.transFigure)

    fig.text(0.500, 0.022,
             "Data: MLB Stats API  +  Baseball Savant / Statcast",
             ha="center", va="center",
             color=COLORS["text_muted"], fontsize=6.5,
             transform=fig.transFigure)


# ── Main card ─────────────────────────────────────────────────────────────────

def make_game_card(audit_result: dict, game_date: date,
                   game_pk: int | None = None) -> Path:
    """
    Build the per-game ABS audit card.
    """
    abs_ch = audit_result.get("abs_challenges", [])
    ua     = audit_result.get("ump_accuracy", {}) or {}

    fig = plt.figure(figsize=(FW, FH), dpi=DPI)
    fig.patch.set_facecolor(COLORS["bg"])

    # ── Header ───────────────────────────────────────────────────────────────
    _draw_header(fig, audit_result, game_date)

    # ── Zone axes: portrait, equal-aspect, left 45 % of figure ───────────────
    # [left, bottom, width, height] in figure fractions.
    # Height = 0.82 - 0.09 = 0.73 of figure = 4.93 in
    # Width  = 0.45 of figure = 5.4 in
    # With equal aspect and data 2.1 × 2.75 ft, height constrains:
    #   scale = 4.93/2.75 = 1.793 in/ft
    #   zone box ≈ 2.54 in wide × 3.59 in tall → correct 17":24" ratio ✓
    ax = fig.add_axes([0.03, 0.090, 0.460, 0.730])
    ax.set_facecolor(COLORS["bg"])
    _draw_zone(ax, abs_ch, ua)

    # ── Stats panel ───────────────────────────────────────────────────────────
    _draw_stats(fig, audit_result)

    # ── Legend ────────────────────────────────────────────────────────────────
    _draw_legend(fig)

    # ── Save ─────────────────────────────────────────────────────────────────
    pk_suffix = f"_{game_pk}" if game_pk else ""
    out_path  = OUTPUT_DIR / f"game_card_{game_date.isoformat()}{pk_suffix}.png"
    plt.savefig(out_path, dpi=DPI, bbox_inches="tight",
                facecolor=COLORS["bg"], pad_inches=0.05)
    plt.close(fig)
    log.info("Saved → %s", out_path)
    return out_path


# Back-compat alias
def make_daily_card(audit_result: dict, game_date: date,
                    game_pk: int | None = None) -> Path:
    return make_game_card(audit_result, game_date, game_pk=game_pk)


# ── Leaderboard ───────────────────────────────────────────────────────────────

def make_leaderboard(leaderboard_df: pd.DataFrame, game_date: date) -> Path | None:
    if leaderboard_df is None or leaderboard_df.empty:
        return None

    agg = (leaderboard_df
           .groupby("team_abbr", as_index=False)
           .agg(challenges=("n_challenges", "sum"),
                overturns=("n_overturns",  "sum")))
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
    fig.patch.set_facecolor(COLORS["bg"])
    ax.set_facecolor(COLORS["bg"])

    bar_colors = [TEAM_COLORS.get(t, COLORS["neutral"]) for t in teams]
    bar_h = max(0.35, min(0.72, 8.0 / n))
    bars  = ax.barh(teams, rates, color=bar_colors,
                    height=bar_h, zorder=3, alpha=0.85)

    ax.xaxis.grid(True, color=COLORS["border"], linewidth=0.5, zorder=0)
    ax.set_axisbelow(True)
    xlim = max(100, max(rates) * 1.22)
    fs   = max(6, min(9, int(200 / n)))

    for bar, rate, cnt in zip(bars, rates, counts):
        ax.text(bar.get_width() + xlim * 0.015,
                bar.get_y() + bar.get_height() / 2,
                f"{rate:.0f}%  ({cnt})",
                va="center", ha="left",
                color=COLORS["text"], fontsize=fs)

    league = sum(agg["overturns"]) / sum(agg["challenges"]) * 100
    ax.axvline(league, color=COLORS["highlight"], linewidth=1.4,
               linestyle="--", label=f"MLB avg {league:.0f}%", zorder=4)
    ax.legend(facecolor=COLORS["surface"], edgecolor=COLORS["border"],
              labelcolor=COLORS["text"], fontsize=8, loc="lower right")
    ax.set_xlabel("ABS Overturn Rate (%)", color=COLORS["text"], fontsize=10)
    ax.set_title(
        f"ABS CHALLENGE LEADERBOARD — {game_date.strftime('%B %-d, %Y').upper()}",
        color=COLORS["text"], fontsize=13, fontweight="bold", pad=12)
    ax.tick_params(colors=COLORS["text"], labelsize=fs)
    ax.yaxis.tick_left()
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(COLORS["border"])
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
                    game_pk: int | None = None) -> dict:
    card = make_game_card(audit_result, game_date, game_pk=game_pk)
    lb   = None
    if (force_leaderboard or game_date.weekday() == 0) and leaderboard_df is not None:
        lb = make_leaderboard(leaderboard_df, game_date)
    return {"daily_card": card, "leaderboard": lb}
