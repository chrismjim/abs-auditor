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
import matplotlib.colors as mcolors
import matplotlib.patches as mpatches
import matplotlib.patheffects as pe
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.lines import Line2D

from src.audit import (
    CORRECT_OVERTURN,
    CORRECT_UPHELD,
    INCORRECT_OVERTURN,
    MISSED_CALL,
)
from src.config import (
    COLORS,
    DAILY_HISTORY,
    DPI,
    FIGURE_HEIGHT_PX,
    FIGURE_WIDTH_PX,
    OUTPUT_DIR,
    TEAM_COLORS,
    ZONE_BOT_FT,
    ZONE_HALF_WIDTH_FT,
    ZONE_TOP_FT,
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

# Standard MLB zone used for the drawn box — must match fetch.py's in_zone check
_SZ_TOP  = ZONE_TOP_FT
_SZ_BOT  = ZONE_BOT_FT

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


# ── Font setup ────────────────────────────────────────────────────────────────

def _setup_font() -> str:
    """Return the best available premium font family."""
    from matplotlib import font_manager as fm
    available = {f.name for f in fm.fontManager.ttflist}
    for font in ("Inter", "Roboto", "Helvetica Neue", "Helvetica", "Gill Sans", "Arial"):
        if font in available:
            return font
    return "sans-serif"


_FONT = _setup_font()


# ── Glow scatter helper ────────────────────────────────────────────────────────

def _scatter_glow(ax: plt.Axes,
                  xs, zs, color: str,
                  size: float = 110,
                  layers: int = 3,
                  zorder: float = 6,
                  edge: bool = False) -> None:
    """Neon-glow scatter: concentric layers from large+transparent to core dot."""
    glow_sizes  = [size * 3.2, size * 2.0, size * 1.35]
    glow_alphas = [0.06,       0.11,        0.20       ]
    for s, a in zip(glow_sizes[-layers:], glow_alphas[-layers:]):
        ax.scatter(xs, zs, s=s, c=color, alpha=a, linewidths=0, zorder=zorder - 0.1)
    kw: dict = dict(linewidths=1.5, edgecolors="white") if edge else dict(linewidths=0)
    ax.scatter(xs, zs, s=size, c=color, alpha=0.95, zorder=zorder, **kw)


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
    Premium gradient header: away-color → dark → home-color band behind
    team abbreviations, score, and subtitle.
    """
    matchup  = audit_result.get("matchup", "")
    away, home = _parse_matchup(matchup)
    score    = audit_result.get("final_score", {}) or {}
    a_sc     = score.get("away")
    h_sc     = score.get("home")
    date_str = game_date.strftime("%B %-d, %Y").upper()

    # ── Gradient band filling the full header region ──────────────────────────
    hax = fig.add_axes([0.0, 0.818, 1.0, 0.182], zorder=1)
    hax.set_axis_off()
    if away and home:
        away_c = mcolors.to_rgb(_tc(away))
        home_c = mcolors.to_rgb(_tc(home))
        dark_c = mcolors.to_rgb("#0d1117")
        cmap_hdr = LinearSegmentedColormap.from_list(
            "hdr", [away_c, dark_c, home_c])
        grad = np.linspace(0, 1, 512).reshape(1, 512)
        hax.imshow(grad, aspect="auto", cmap=cmap_hdr,
                   alpha=0.45, extent=[0, 1, 0, 1], zorder=1)
    hax.set_facecolor(COLORS["bg"])

    # ── Team / score row ─────────────────────────────────────────────────────
    if away and home:
        fig.text(0.275, 0.895, away,
                 ha="center", va="center",
                 color=_tc(away), fontsize=30, fontweight="bold",
                 fontfamily=_FONT,
                 path_effects=[pe.withStroke(linewidth=3, foreground="#0d1117")],
                 transform=fig.transFigure, zorder=10)
        if a_sc is not None and h_sc is not None:
            fig.text(0.500, 0.895, f"{a_sc}  –  {h_sc}",
                     ha="center", va="center",
                     color=COLORS["text"], fontsize=24, fontweight="bold",
                     fontfamily=_FONT,
                     transform=fig.transFigure, zorder=10)
        else:
            fig.text(0.500, 0.895, "vs",
                     ha="center", va="center",
                     color=COLORS["text_muted"], fontsize=18,
                     fontfamily=_FONT,
                     transform=fig.transFigure, zorder=10)
        fig.text(0.725, 0.895, home,
                 ha="center", va="center",
                 color=_tc(home), fontsize=30, fontweight="bold",
                 fontfamily=_FONT,
                 path_effects=[pe.withStroke(linewidth=3, foreground="#0d1117")],
                 transform=fig.transFigure, zorder=10)
    else:
        fig.text(0.500, 0.895, "MLB ABS AUDIT",
                 ha="center", va="center",
                 color=COLORS["text"], fontsize=22, fontweight="bold",
                 fontfamily=_FONT,
                 transform=fig.transFigure, zorder=10)

    # ── Subtitle ─────────────────────────────────────────────────────────────
    fig.text(0.500, 0.840,
             f"ABS CHALLENGE AUDIT  ·  {date_str}",
             ha="center", va="center",
             color=COLORS["text_muted"], fontsize=8.5,
             fontfamily=_FONT,
             transform=fig.transFigure, zorder=10)

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

    # ── Radial vignette (darkens display edges, spotlight on zone) ────────────
    vx = np.linspace(-_DX, _DX, 200)
    vz = np.linspace(_DZ_BOT, _DZ_TOP, 200)
    VX, VZ = np.meshgrid(vx, vz)
    cx_v, cz_v = 0.0, (_SZ_BOT + _SZ_TOP) / 2.0
    rad = np.sqrt(((VX - cx_v) / (_DX * 1.1))**2
                  + ((VZ - cz_v) / ((_DZ_TOP - _DZ_BOT) / 1.6))**2)
    vignette = np.clip(rad - 0.3, 0, 1) * 0.55
    ax.imshow(vignette, extent=[-_DX, _DX, _DZ_BOT, _DZ_TOP],
              origin="lower", aspect="auto", cmap="Greys",
              alpha=0.85, zorder=1, interpolation="bilinear")

    # ── 5-sided home plate (catcher's view) ───────────────────────────────────
    pw       = ZONE_HALF_WIDTH_FT
    ph       = 0.15       # height of plate rectangle
    pp       = 0.075      # depth from rectangle bottom to pointed tip
    plate_base = _SZ_BOT - ph - 0.05
    plate_verts = np.array([
        [-pw, plate_base + ph],   # back-left
        [-pw, plate_base + pp],   # front-left
        [ 0,  plate_base],        # point (home)
        [ pw, plate_base + pp],   # front-right
        [ pw, plate_base + ph],   # back-right
    ])
    plate_patch = plt.Polygon(
        plate_verts, closed=True,
        facecolor="#1a2030", edgecolor="#3d4f6b",
        linewidth=1.2, zorder=2,
    )
    ax.add_patch(plate_patch)
    ax.text(0, plate_base + (ph + pp) / 2 + 0.01, "HOME PLATE",
            ha="center", va="center",
            color="#4b5563", fontsize=4.0, fontweight="bold",
            fontfamily=_FONT)

    # ── Zone fill + interior subtle gradient ──────────────────────────────────
    zone_fill = mpatches.Rectangle(
        (-ZONE_HALF_WIDTH_FT, _SZ_BOT),
        ZONE_HALF_WIDTH_FT * 2, _SZ_TOP - _SZ_BOT,
        linewidth=0, facecolor="#161b22", zorder=2,
    )
    ax.add_patch(zone_fill)

    # Subtle blue interior gradient — depth cue (lighter at centre)
    zg = np.linspace(0.0, 0.12, 80).reshape(80, 1)
    grad_arr = np.tile(zg, (1, 60))
    ax.imshow(grad_arr,
              extent=[-ZONE_HALF_WIDTH_FT, ZONE_HALF_WIDTH_FT, _SZ_BOT, _SZ_TOP],
              origin="lower", aspect="auto", cmap="Blues",
              alpha=0.18, zorder=3, interpolation="bilinear")

    w  = ZONE_HALF_WIDTH_FT
    dz = (_SZ_TOP - _SZ_BOT) / 3
    dx = w * 2 / 3
    for i in (1, 2):
        ax.plot([-w, w], [_SZ_BOT + i * dz]*2, color="#2d333b", lw=0.8, zorder=4)
        ax.plot([-w + i*dx]*2, [_SZ_BOT, _SZ_TOP], color="#2d333b", lw=0.8, zorder=4)

    zone_border = mpatches.Rectangle(
        (-ZONE_HALF_WIDTH_FT, _SZ_BOT),
        ZONE_HALF_WIDTH_FT * 2, _SZ_TOP - _SZ_BOT,
        linewidth=2.0, edgecolor="#6e7681", facecolor="none", zorder=4,
    )
    ax.add_patch(zone_border)

    # ── Build an inverted clip patch for wrong strikes ────────────────────────
    _outer = np.array([
        [-_DX, _DZ_BOT], [_DX, _DZ_BOT], [_DX, _DZ_TOP], [-_DX, _DZ_TOP], [-_DX, _DZ_BOT],
    ])
    _inner = np.array([                                       # reversed winding = hole
        [-ZONE_HALF_WIDTH_FT, _SZ_BOT],
        [-ZONE_HALF_WIDTH_FT, _SZ_TOP],
        [ ZONE_HALF_WIDTH_FT, _SZ_TOP],
        [ ZONE_HALF_WIDTH_FT, _SZ_BOT],
        [-ZONE_HALF_WIDTH_FT, _SZ_BOT],
    ])
    from matplotlib.path import Path as MPath
    _codes_fn = lambda pts: (
        [MPath.MOVETO] + [MPath.LINETO] * (len(pts) - 2) + [MPath.CLOSEPOLY]
    )
    outside_clip = mpatches.PathPatch(
        MPath(np.vstack([_outer, _inner]),
              _codes_fn(_outer) + _codes_fn(_inner)),
        transform=ax.transData, visible=False,
    )
    ax.add_patch(outside_clip)

    # ── Wrong strikes — glow dots clipped to outside-zone region ─────────────
    ws = ua.get("wrong_strike_coords", [])
    if ws:
        xs_w, zs_w = zip(*ws)
        # Glow layers (large → transparent, then core)
        for gsize, galpha in [(80, 0.05), (45, 0.10), (20, 0.80)]:
            sc = ax.scatter(xs_w, zs_w, s=gsize, color="#f85149", alpha=galpha,
                            linewidths=0, zorder=5)
            sc.set_clip_path(outside_clip)

    # ── Wrong balls — glow dots inside zone ───────────────────────────────────
    wb = ua.get("wrong_ball_coords", [])
    if wb:
        xb, zb = zip(*wb)
        for gsize, galpha in [(80, 0.05), (45, 0.10), (20, 0.80)]:
            ax.scatter(xb, zb, s=gsize, color="#e3b341", alpha=galpha,
                       linewidths=0, zorder=5)

    # ── ABS challenge dots — neon glow ────────────────────────────────────────
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

        # Neon glow layers + core with white ring
        _scatter_glow(ax, [px], [pz], color, size=110, layers=3, zorder=6, edge=True)

        label = f"{half}{inn}" + (f"\n{cnt_str}" if cnt_str else "")
        ax.annotate(
            label,
            xy=(px, pz), xytext=(0, 9),
            textcoords="offset points",
            ha="center", va="bottom",
            color=color, fontsize=5.5, fontweight="bold",
            fontfamily=_FONT,
            zorder=8,
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
        # ── Accuracy progress bar ─────────────────────────────────────────────
        BAR_W = 0.445
        BAR_H = 0.018
        bar_y = y - BAR_H - 0.005
        # Background track
        fig.add_artist(mpatches.FancyBboxPatch(
            (X, bar_y), BAR_W, BAR_H,
            boxstyle="round,pad=0.003",
            facecolor="#1c2128", edgecolor=COLORS["border"],
            linewidth=0.8, transform=fig.transFigure, zorder=3,
        ))
        # Filled portion (clamped to BAR_W)
        fill_w = min(BAR_W, BAR_W * (ump_pct / 100.0))
        if fill_w > 0.004:
            fig.add_artist(mpatches.FancyBboxPatch(
                (X, bar_y), fill_w, BAR_H,
                boxstyle="round,pad=0.003",
                facecolor=pct_color, edgecolor="none",
                linewidth=0, transform=fig.transFigure, zorder=4,
            ))
        y -= BAR_H + 0.024   # advance cursor past bar + gap

    if ws:
        txt(f"● {ws} wrong strike{'s' if ws != 1 else ''}",
            size=8, color=COLORS["missed"])
        step(0.75, small=True)
    if wb:
        txt(f"● {wb} wrong ball{'s' if wb != 1 else ''}",
            size=8, color=COLORS["highlight"])
        step(0.75, small=True)

    # ── Favor metric ──────────────────────────────────────────────────────────
    favor = ua.get("favor_score")
    if favor is not None and favor != 0:
        if favor > 0:
            favor_color = "#f85149"   # red — pitcher-friendly (extra strikes)
            favor_txt   = f"+{favor} pitcher favor"
        else:
            favor_color = "#3fb950"   # green — batter-friendly (extra balls)
            favor_txt   = f"{favor} batter favor"
        txt(f"● {favor_txt}", size=7.5, color=favor_color)
        step(0.75, small=True)

    step(0.40)   # spacer

    # ── Game rates ────────────────────────────────────────────────────────────
    ch_rate = summary.get("challenge_rate", 0)
    ot_rate = summary.get("overturn_rate", 0)
    total_abs = summary.get("total_challenges", 0)
    if ump_tot >= 5:
        txt("GAME RATES", size=7, color=COLORS["text_muted"], weight="bold")
        step(0.55)
        txt(f"Challenge rate  {ch_rate:.1f}% of called pitches",
            size=7.5, color=COLORS["text"])
        step(0.70, small=True)
        if total_abs > 0:
            ot_color = (COLORS["correct"] if ot_rate >= 55 else
                        COLORS["highlight"] if ot_rate >= 40 else
                        COLORS["text_muted"])
            txt(f"Overturn rate   {ot_rate:.0f}%  ({summary.get('overturned', 0)}/{total_abs})",
                size=7.5, color=ot_color)
            step(0.70, small=True)
        step(0.30)

    # ── ABS CHALLENGES ────────────────────────────────────────────────────────
    if abs_ch:
        txt("ABS CHALLENGES", size=7, color=COLORS["text_muted"], weight="bold")
        step(0.55)

        for ch in abs_ch:
            outcome  = ch.get("outcome")
            color    = OUTCOME_COLOR.get(outcome, COLORS["neutral"])
            label    = OUTCOME_LABEL.get(outcome, "—")
            half     = "T" if ch.get("half_inning") == "top" else "B"
            inn      = ch.get("inning", "?")
            pitcher  = _last(ch.get("pitcher"))
            batter   = _last(ch.get("batter"))
            cnt      = ch.get("count") or {}
            b, s     = cnt.get("balls"), cnt.get("strikes")
            cnt_str  = f" {b}-{s}" if b is not None else ""
            edge_d   = ch.get("edge_dist")
            orig     = (ch.get("original_call") or "").lower()
            call_lbl = "CS" if "called strike" in orig else "Ball"
            runners  = ch.get("runners_on")

            # Runners on base indicator
            if runners is not None:
                runner_icons = ["—", "1on", "2on", "LOB"][min(runners, 3)]
            else:
                runner_icons = ""

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
                     f"{half}{inn}{cnt_str}  {pitcher} vs {batter}",
                     ha="left", va="top",
                     color=COLORS["text"], fontsize=8, fontweight="bold",
                     transform=fig.transFigure)
            step(0.60, small=True)
            runner_part = f"  {runner_icons}" if runner_icons else ""
            txt(f"    {call_lbl}  ·  {label}{dist}{runner_part}",
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

    plt.rcParams["font.family"] = _FONT
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


# ── Umpire accuracy season leaderboard ───────────────────────────────────────

def make_ump_accuracy_leaderboard(season_stats: dict, game_date: date) -> Path | None:
    """
    Bar chart of every umpire's full-game called-pitch accuracy for the season,
    ranked best → worst.  Only includes umps with ≥ 50 total called pitches.
    """
    ump_data = season_stats.get("umpire_stats", {})
    rows = []
    for name, u in ump_data.items():
        tc = u.get("total_called", 0)
        if tc < 50:
            continue
        rows.append({
            "name":    name.split()[-1],   # last name only
            "pct":     u.get("accuracy_pct", 0),
            "total":   tc,
            "ws":      u.get("wrong_strikes", 0),
            "wb":      u.get("wrong_balls", 0),
        })

    if not rows:
        return None

    rows.sort(key=lambda r: r["pct"])    # ascending: worst at top, best at bottom
    n    = len(rows)
    names = [r["name"] for r in rows]
    pcts  = [r["pct"]  for r in rows]
    totals= [r["total"] for r in rows]

    fig_h = max(4.5, min(14.0, n * 0.42 + 1.5))
    fig, ax = plt.subplots(figsize=(FW, fig_h), dpi=DPI)
    fig.patch.set_facecolor(COLORS["bg"])
    ax.set_facecolor(COLORS["bg"])

    bar_colors = [
        COLORS["correct"]   if p >= 95 else
        COLORS["highlight"] if p >= 88 else
        COLORS["missed"]
        for p in pcts
    ]
    bar_h = max(0.35, min(0.72, 8.0 / n))
    bars  = ax.barh(names, pcts, color=bar_colors, height=bar_h, zorder=3, alpha=0.85)

    ax.xaxis.grid(True, color=COLORS["border"], linewidth=0.5, zorder=0)
    ax.set_axisbelow(True)
    xlim = max(100, max(pcts) * 1.12)
    fs   = max(6, min(9, int(220 / n)))

    for bar, pct, total, r in zip(bars, pcts, totals, rows):
        favor = r["ws"] - r["wb"]
        bias  = f"  +{favor}P" if favor > 0 else (f"  {favor}B" if favor < 0 else "")
        ax.text(bar.get_width() + xlim * 0.012,
                bar.get_y() + bar.get_height() / 2,
                f"{pct:.1f}%  ({total} pitches){bias}",
                va="center", ha="left",
                color=COLORS["text"], fontsize=fs)

    league_avg = sum(r["pct"] * r["total"] for r in rows) / sum(r["total"] for r in rows)
    ax.axvline(league_avg, color=COLORS["highlight"], linewidth=1.4,
               linestyle="--", label=f"MLB avg {league_avg:.1f}%", zorder=4)
    ax.legend(facecolor=COLORS["surface"], edgecolor=COLORS["border"],
              labelcolor=COLORS["text"], fontsize=8, loc="lower right")
    ax.set_xlabel("Called-pitch accuracy (%)", color=COLORS["text"], fontsize=10)
    ax.set_title(
        f"HP UMPIRE ACCURACY LEADERBOARD — {game_date.strftime('%B %-d, %Y').upper()}",
        color=COLORS["text"], fontsize=13, fontweight="bold", pad=12)
    ax.tick_params(colors=COLORS["text"], labelsize=fs)
    ax.yaxis.tick_left()
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    for sp in ("left", "bottom"):
        ax.spines[sp].set_color(COLORS["border"])
    ax.set_xlim(max(80, min(pcts) - 3), xlim)

    fig.text(0.50, 0.005,
             "Based on called strikes + called balls vs. standard zone  |  2026 season",
             ha="center", va="bottom",
             color=COLORS["text_muted"], fontsize=7,
             transform=fig.transFigure)

    out_path = OUTPUT_DIR / f"ump_leaderboard_{game_date.isoformat()}.png"
    plt.savefig(out_path, dpi=DPI, bbox_inches="tight", facecolor=COLORS["bg"])
    plt.close(fig)
    log.info("Saved ump leaderboard → %s", out_path)
    return out_path


# ── Accuracy trend chart ──────────────────────────────────────────────────────

def make_trend_chart(game_date: date, lookback_days: int = 14) -> Path | None:
    """
    Dual-axis line chart showing rolling daily called-pitch accuracy (left axis)
    and ABS overturn rate (right axis) over the last `lookback_days` days.
    """
    import json as _json
    if not DAILY_HISTORY.exists():
        return None

    try:
        history = _json.loads(DAILY_HISTORY.read_text())
    except Exception:
        return None

    # Filter to lookback window, require accuracy data
    history = [e for e in history if e.get("accuracy_pct") is not None]
    history = history[-lookback_days:]
    if len(history) < 2:
        return None

    dates       = [e["date"] for e in history]
    accuracy    = [e["accuracy_pct"] for e in history]
    overturn    = [e.get("overturn_rate", 0) for e in history]
    x           = list(range(len(dates)))
    short_dates = [d[5:] for d in dates]   # "MM-DD"

    fig, ax1 = plt.subplots(figsize=(FW, 4.0), dpi=DPI)
    fig.patch.set_facecolor(COLORS["bg"])
    ax1.set_facecolor(COLORS["bg"])

    # Accuracy line
    ax1.plot(x, accuracy, color=COLORS["correct"], linewidth=2.0,
             marker="o", markersize=4, label="Called accuracy %", zorder=3)
    ax1.fill_between(x, accuracy, alpha=0.15, color=COLORS["correct"])
    ax1.set_ylabel("Called-pitch accuracy (%)", color=COLORS["correct"], fontsize=9)
    ax1.tick_params(axis="y", colors=COLORS["correct"])
    ax1.set_ylim(max(80, min(accuracy) - 2), 100)

    # Overturn rate on right axis
    ax2 = ax1.twinx()
    ax2.set_facecolor(COLORS["bg"])
    ax2.plot(x, overturn, color=COLORS["highlight"], linewidth=2.0,
             marker="s", markersize=4, linestyle="--",
             label="ABS overturn rate %", zorder=3)
    ax2.set_ylabel("ABS overturn rate (%)", color=COLORS["highlight"], fontsize=9)
    ax2.tick_params(axis="y", colors=COLORS["highlight"])
    ax2.set_ylim(0, 100)

    # League-average reference lines
    avg_acc = sum(accuracy) / len(accuracy)
    avg_ot  = sum(o for o in overturn if o) / max(1, sum(1 for o in overturn if o))
    ax1.axhline(avg_acc, color=COLORS["correct"], linewidth=0.8, linestyle=":", alpha=0.5)
    ax2.axhline(avg_ot, color=COLORS["highlight"], linewidth=0.8, linestyle=":", alpha=0.5)

    ax1.set_xticks(x)
    ax1.set_xticklabels(short_dates, rotation=45, ha="right",
                        color=COLORS["text"], fontsize=7)
    ax1.set_xlim(-0.5, len(x) - 0.5)

    for sp in ("top",):
        ax1.spines[sp].set_visible(False)
        ax2.spines[sp].set_visible(False)
    for sp in ("left", "bottom", "right"):
        ax1.spines[sp].set_color(COLORS["border"])
        ax2.spines[sp].set_color(COLORS["border"])
    ax1.xaxis.grid(True, color=COLORS["border"], linewidth=0.4, alpha=0.5)

    # Combined legend
    lines  = ax1.get_lines() + ax2.get_lines()
    labels = [l.get_label() for l in lines]
    ax1.legend(lines, labels, facecolor=COLORS["surface"], edgecolor=COLORS["border"],
               labelcolor=COLORS["text"], fontsize=8, loc="lower left")

    fig.suptitle(
        f"MLB ABS ACCURACY TREND — last {len(history)} days",
        color=COLORS["text"], fontsize=11, fontweight="bold", y=1.01,
    )
    fig.text(0.50, -0.04,
             "Called accuracy = correct ball/strike calls ÷ all called pitches",
             ha="center", va="top",
             color=COLORS["text_muted"], fontsize=7,
             transform=fig.transFigure)

    fig.tight_layout()
    out_path = OUTPUT_DIR / f"trend_{game_date.isoformat()}.png"
    plt.savefig(out_path, dpi=DPI, bbox_inches="tight",
                facecolor=COLORS["bg"], pad_inches=0.10)
    plt.close(fig)
    log.info("Saved trend chart → %s", out_path)
    return out_path


# ── Entry point ───────────────────────────────────────────────────────────────

def generate_images(audit_result: dict, season_stats: dict,
                    game_date: date,
                    leaderboard_df: "pd.DataFrame | None" = None,
                    force_leaderboard: bool = False,
                    game_pk: int | None = None) -> dict:
    card = make_game_card(audit_result, game_date, game_pk=game_pk)

    is_monday = game_date.weekday() == 0
    do_lb     = force_leaderboard or is_monday

    # ABS challenge leaderboard (team/batter overturn rates)
    abs_lb = None
    if do_lb and leaderboard_df is not None:
        abs_lb = make_leaderboard(leaderboard_df, game_date)

    # Umpire accuracy leaderboard (season, Mondays)
    ump_lb = None
    if do_lb and season_stats:
        ump_lb = make_ump_accuracy_leaderboard(season_stats, game_date)

    # Accuracy trend chart (Mondays)
    trend = None
    if do_lb:
        trend = make_trend_chart(game_date)

    return {
        "daily_card":       card,
        "leaderboard":      abs_lb,
        "ump_leaderboard":  ump_lb,
        "trend":            trend,
    }
