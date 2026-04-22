"""
ABS Auditor — visualization (v5, light portrait).

Portrait 9:16 cream-themed game card designed for social shareability
(Instagram / Twitter story size).

Layout (2160 × 3840 px):
  Header       : full-width header with team-coloured abbrs + score
  Zone         : large, centred strike zone with called-pitch dots and
                 ABS-challenge rings
  Zone legend  : pill legend immediately under the zone
  Stats cards  : two side-by-side surface cards — UMPIRE (accuracy donut +
                 miss summary) and GAME RATES (two rate gauges)
  Challenges   : colored-dot list with outcome-badge check/cross
  Replay + Data footer
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
    MISSED_CALL,
)
from src.config import (
    CARD_DPI,
    CARD_HEIGHT_PX,
    CARD_WIDTH_PX,
    COLORS,
    DAILY_HISTORY,
    DPI,
    FIGURE_HEIGHT_PX,
    FIGURE_WIDTH_PX,
    MAX_CHALLENGES_ON_CARD,
    OUTPUT_DIR,
    TEAM_COLORS,
    ZONE_BOT_FT,
    ZONE_HALF_WIDTH_FT,
    ZONE_TOP_FT,
)

log = logging.getLogger(__name__)

# Portrait card (new design)
CARD_W = CARD_WIDTH_PX  / CARD_DPI   # 6.75 in
CARD_H = CARD_HEIGHT_PX / CARD_DPI   # 12.00 in

# Legacy landscape (used by leaderboard / trend charts)
FW = FIGURE_WIDTH_PX / DPI   # 12.0 in
FH = FIGURE_HEIGHT_PX / DPI  # 6.75 in

# ── Zone display parameters ───────────────────────────────────────────────────
# Data window — a little margin past the zone edges so off-zone dots render
# fully (no half-circles clipped by the axes frame). The ~2" of slack on each
# side of the ±8.5" zone is enough for all real edge pitches.
_DX      = 1.10   # ± ft shown on X axis
_DZ_BOT  = 1.25   # ft — bottom of display
_DZ_TOP  = 3.80   # ft — top of display

# Standard MLB zone — must match fetch.py's in_zone check
_SZ_TOP  = ZONE_TOP_FT
_SZ_BOT  = ZONE_BOT_FT

# Outcome colours / labels (use the palette from config for consistency)
OUTCOME_COLOR = {
    CORRECT_OVERTURN: COLORS["correct"],   # green
    CORRECT_UPHELD:   COLORS["neutral"],   # warm gray
    MISSED_CALL:      COLORS["missed"],    # red
    None:               COLORS["neutral"],
}
OUTCOME_LABEL = {
    CORRECT_OVERTURN: "Overturned",
    CORRECT_UPHELD:   "Upheld",
    MISSED_CALL:      "Missed",
    None:               "—",
}
# Outcomes that count as "correct challenge" on the result badge
_PASS_OUTCOMES = {CORRECT_OVERTURN, CORRECT_UPHELD}


# ── Font setup ────────────────────────────────────────────────────────────────

def _setup_font() -> str:
    """
    Prefer Apple's SF Pro (SFNS.ttf — registered as 'System Font') which is
    the same typeface used on apple.com. Falls back gracefully on non-macOS
    systems or when the font cannot be loaded.
    """
    from matplotlib import font_manager as fm
    import os
    sfns_path = "/System/Library/Fonts/SFNS.ttf"
    if os.path.exists(sfns_path):
        try:
            fm.fontManager.addfont(sfns_path)
            return "System Font"
        except Exception:
            pass
    available = {f.name for f in fm.fontManager.ttflist}
    for font in ("Inter", "Roboto", "Helvetica Neue", "Helvetica", "Gill Sans", "Arial"):
        if font in available:
            return font
    return "sans-serif"


_FONT = _setup_font()

# Figure aspect ratio for legend icon correction (portrait 9:16).
# mpatches.Circle with transform=fig.transFigure draws in figure-fraction space
# where 1 unit x ≠ 1 unit y (physically), so we store the ratio once and use
# mpatches.Ellipse everywhere to keep icons visually round.
_FIG_ASPECT = CARD_W / CARD_H   # 6.75 / 12.00 ≈ 0.5625


# ── Glow scatter helper ────────────────────────────────────────────────────────

def _scatter_glow(ax: plt.Axes,
                  xs, zs, color: str,
                  size: float = 110,
                  layers: int = 3,
                  zorder: float = 6,
                  edge: bool = False) -> None:
    """Neon-glow scatter: concentric layers from large+transparent to core dot."""
    glow_sizes  = [size * 3.5, size * 2.2, size * 1.4]
    glow_alphas = [0.08,       0.15,        0.30       ]
    for s, a in zip(glow_sizes[-layers:], glow_alphas[-layers:]):
        ax.scatter(xs, zs, s=s, c=color, alpha=a, linewidths=0, zorder=zorder - 0.1)
    kw: dict = dict(linewidths=1.5, edgecolors="white") if edge else dict(linewidths=0)
    ax.scatter(xs, zs, s=size, c=color, alpha=0.95, zorder=zorder, **kw)
    if edge:
        # Hot white core to simulate light source
        ax.scatter(xs, zs, s=size * 0.15, c="white", alpha=0.9, zorder=zorder + 0.1, linewidths=0)


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
    Portrait header: team abbreviations in team colors flanking a winner-
    coloured score, with a subtitle using middle-dot separators.
    """
    matchup    = audit_result.get("matchup", "")
    away, home = _parse_matchup(matchup)
    score      = audit_result.get("final_score", {}) or {}
    a_sc       = score.get("away")
    h_sc       = score.get("home")
    date_str   = game_date.strftime("%b %-d, %Y").upper()   # APR 14, 2026

    # Top accent strip
    if away and home:
        fig.add_artist(mpatches.Rectangle(
            (0.0, 0.9955), 0.5, 0.0045, transform=fig.transFigure,
            color=_tc(away), zorder=5,
        ))
        fig.add_artist(mpatches.Rectangle(
            (0.5, 0.9955), 0.5, 0.0045, transform=fig.transFigure,
            color=_tc(home), zorder=5,
        ))
    else:
        fig.add_artist(mpatches.Rectangle(
            (0.0, 0.9955), 1.0, 0.0045, transform=fig.transFigure,
            color=COLORS["border"], zorder=5,
        ))

    if away and home:
        # Team abbreviations flanking the score
        fig.text(0.215, 0.965, away,
                 ha="center", va="center",
                 color=_tc(away), fontsize=44, fontweight="900",
                 fontfamily=_FONT,
                 transform=fig.transFigure, zorder=10)
        fig.text(0.785, 0.965, home,
                 ha="center", va="center",
                 color=_tc(home), fontsize=44, fontweight="900",
                 fontfamily=_FONT,
                 transform=fig.transFigure, zorder=10)

        # Winner-coloured score (loser muted)
        if a_sc is not None and h_sc is not None:
            if a_sc > h_sc:
                a_color, h_color = _tc(away), COLORS["text_muted"]
            elif h_sc > a_sc:
                a_color, h_color = COLORS["text_muted"], _tc(home)
            else:
                a_color = h_color = COLORS["text"]
            fig.text(0.455, 0.965, f"{a_sc}",
                     ha="center", va="center",
                     color=a_color, fontsize=42, fontweight="900",
                     fontfamily=_FONT,
                     transform=fig.transFigure, zorder=10)
            fig.text(0.500, 0.965, "–",
                     ha="center", va="center",
                     color=COLORS["text_muted"], fontsize=30,
                     fontweight="400",
                     fontfamily=_FONT,
                     transform=fig.transFigure, zorder=10)
            fig.text(0.545, 0.965, f"{h_sc}",
                     ha="center", va="center",
                     color=h_color, fontsize=42, fontweight="900",
                     fontfamily=_FONT,
                     transform=fig.transFigure, zorder=10)
        else:
            fig.text(0.500, 0.965, "vs",
                     ha="center", va="center",
                     color=COLORS["text_muted"], fontsize=22,
                     fontfamily=_FONT,
                     transform=fig.transFigure, zorder=10)

    else:
        fig.text(0.500, 0.965, "MLB ABS AUDIT",
                 ha="center", va="center",
                 color=COLORS["text"], fontsize=40, fontweight="900",
                 fontfamily=_FONT,
                 transform=fig.transFigure, zorder=10)

    # Subtitle — category label in regular weight, date bold (the date is
    # the anchor; the category just provides scaffolding).
    fig.text(0.500, 0.938,
             "ABS CHALLENGE AUDIT",
             ha="right", va="center",
             color=COLORS["text_muted"], fontsize=10.5,
             fontweight="normal",
             fontfamily=_FONT,
             transform=fig.transFigure, zorder=10)
    fig.text(0.506, 0.938,
             "·",
             ha="center", va="center",
             color=COLORS["border"], fontsize=14,
             fontweight="normal",
             fontfamily=_FONT,
             transform=fig.transFigure, zorder=10)
    fig.text(0.512, 0.938,
             date_str,
             ha="left", va="center",
             color=COLORS["text"], fontsize=10.5,
             fontweight="bold",
             fontfamily=_FONT,
             transform=fig.transFigure, zorder=10)

    # Hairline divider
    fig.add_artist(mpatches.Rectangle(
        (0.06, 0.923), 0.88, 0.0010,
        transform=fig.transFigure,
        color=COLORS["border"], zorder=3,
    ))


# ── Strike-zone diagram (light theme) ─────────────────────────────────────────

def _draw_zone(ax: plt.Axes,
               abs_challenges: list[dict],
               ump_accuracy: dict) -> None:
    """
    Catcher's-view strike zone on a cream background:
      • Red dots    — every wrong strike (CS outside zone)
      • Indigo dots — every wrong ball   (ball inside zone)
      • Large ringed marker — each ABS challenge (outcome colour)
    """
    ua = ump_accuracy or {}

    ax.set_facecolor(COLORS["bg"])
    ax.set_xlim(-_DX, _DX)
    ax.set_ylim(_DZ_BOT, _DZ_TOP)
    ax.set_aspect("equal", adjustable="box")
    ax.axis("off")

    pw = ZONE_HALF_WIDTH_FT

    # ── Home plate (catcher's view) ───────────────────────────────────────────
    ph       = 0.13
    pp       = 0.07
    plate_base = _SZ_BOT - ph - 0.05
    plate_verts = np.array([
        [-pw, plate_base + ph],
        [-pw, plate_base + pp],
        [ 0,  plate_base],
        [ pw, plate_base + pp],
        [ pw, plate_base + ph],
    ])
    # Home plate — hairline stroke only (no fill) so it reads at the same
    # visual weight as the zone frame instead of competing with it.
    ax.add_patch(plt.Polygon(
        plate_verts, closed=True,
        facecolor="none", edgecolor=COLORS["zone_edge"],
        linewidth=1.0, alpha=0.45, zorder=2,
    ))

    # ── Zone fill + interior grid ─────────────────────────────────────────────
    ax.add_patch(mpatches.Rectangle(
        (-pw, _SZ_BOT), pw * 2, _SZ_TOP - _SZ_BOT,
        linewidth=0, facecolor=COLORS["zone_fill"], alpha=0.55, zorder=2,
    ))

    # Interior 3×3 grid — very light so it guides the eye without competing
    # with the pitch markers. Previously lw=0.9, no alpha (too prominent).
    dz = (_SZ_TOP - _SZ_BOT) / 3
    dx = pw * 2 / 3
    for i in (1, 2):
        ax.plot([-pw, pw], [_SZ_BOT + i * dz]*2,
                color=COLORS["border"], lw=0.6, alpha=0.45, zorder=4)
        ax.plot([-pw + i*dx]*2, [_SZ_BOT, _SZ_TOP],
                color=COLORS["border"], lw=0.6, alpha=0.45, zorder=4)

    # Zone border — slightly thicker so the frame is unambiguously the hero
    ax.add_patch(mpatches.Rectangle(
        (-pw, _SZ_BOT), pw * 2, _SZ_TOP - _SZ_BOT,
        linewidth=2.2, edgecolor=COLORS["zone_edge"], facecolor="none",
        zorder=4,
    ))

    # ── Wrong strikes — red dots outside zone ────────────────────────────────
    ws = ua.get("wrong_strike_coords") or []
    if ws:
        try:
            xs_w, zs_w = zip(*ws)
            ax.scatter(xs_w, zs_w, s=95, color=COLORS["missed"],
                       alpha=0.85, linewidths=0, zorder=5)
        except (ValueError, TypeError):
            pass

    # ── Wrong balls — amber dots inside zone ─────────────────────────────────
    wb = ua.get("wrong_ball_coords") or []
    if wb:
        try:
            xb, zb = zip(*wb)
            ax.scatter(xb, zb, s=95, color=COLORS["accent"],
                       alpha=0.85, linewidths=0, zorder=5)
        except (ValueError, TypeError):
            pass

    # ── ABS challenge markers with collision-avoiding labels ──────────────────
    placed_label_regions: list[tuple[float, float, float, float]] = []

    # Typographic offsets ≈ 1/72 in; at ~2.0 in/ft scale → 0.007 ft / pt.
    _PT_TO_FT   = 0.0070
    _LABEL_W_FT = 0.24
    _LABEL_H_FT = 0.22

    _offset_candidates = [
        (0,  12, "center", "bottom"),
        (0, -14, "center", "top"),
        (16,  2, "left",   "center"),
        (-16, 2, "right",  "center"),
        (14,  12, "left",   "bottom"),
        (-14, 12, "right",  "bottom"),
        (14, -14, "left",   "top"),
        (-14,-14, "right",  "top"),
    ]

    def _label_bbox(px, pz, off_x, off_y, ha_, va_):
        ax_x = px + off_x * _PT_TO_FT
        ax_z = pz + off_y * _PT_TO_FT
        if ha_ == "center":
            xmin, xmax = ax_x - _LABEL_W_FT / 2, ax_x + _LABEL_W_FT / 2
        elif ha_ == "left":
            xmin, xmax = ax_x, ax_x + _LABEL_W_FT
        else:
            xmin, xmax = ax_x - _LABEL_W_FT, ax_x
        if va_ == "bottom":
            zmin, zmax = ax_z, ax_z + _LABEL_H_FT
        elif va_ == "top":
            zmin, zmax = ax_z - _LABEL_H_FT, ax_z
        else:
            zmin, zmax = ax_z - _LABEL_H_FT / 2, ax_z + _LABEL_H_FT / 2
        return xmin, xmax, zmin, zmax

    def _overlaps(b, regions):
        xmin, xmax, zmin, zmax = b
        for (rxmin, rxmax, rzmin, rzmax) in regions:
            if xmin < rxmax and xmax > rxmin and zmin < rzmax and zmax > rzmin:
                return True
        return False

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
        b_, s_  = cnt.get("balls"), cnt.get("strikes")
        cnt_str = f"{b_}-{s_}" if b_ is not None else ""

        # ABS marker: colored outer ring, cream fill, small colored dot inside
        ax.scatter([px], [pz], s=300, facecolor=COLORS["bg"],
                   edgecolors=color, linewidths=3.2, zorder=7)
        ax.scatter([px], [pz], s=60, color=color, linewidths=0, zorder=8)

        chosen = _offset_candidates[0]
        for cand in _offset_candidates:
            ox, oy, ha_, va_ = cand
            bbox = _label_bbox(px, pz, ox, oy, ha_, va_)
            if not _overlaps(bbox, placed_label_regions):
                chosen = cand
                placed_label_regions.append(bbox)
                break
        else:
            ox, oy, ha_, va_ = chosen
            placed_label_regions.append(_label_bbox(px, pz, ox, oy, ha_, va_))

        ox, oy, ha_, va_ = chosen
        label = f"{half}{inn}" + (f"\n{cnt_str}" if cnt_str else "")
        ax.annotate(
            label,
            xy=(px, pz), xytext=(ox, oy),
            textcoords="offset points",
            ha=ha_, va=va_,
            color=COLORS["text"], fontsize=9, fontweight="bold",
            fontfamily=_FONT,
            zorder=10,
            path_effects=[pe.withStroke(linewidth=2.8,
                                         foreground=COLORS["bg"],
                                         alpha=0.95)],
        )


# ── Section helpers ───────────────────────────────────────────────────────────

def _sec_header(fig: plt.Figure, label: str, y: float,
                x: float = 0.08, size: float = 10) -> None:
    """Small muted all-caps section heading."""
    fig.text(x, y, label,
             ha="left", va="center",
             color=COLORS["text_muted"], fontsize=size,
             fontweight="bold", fontfamily=_FONT,
             transform=fig.transFigure, zorder=5)


def _pct_donut(fig: plt.Figure, cx: float, cy: float,
               radius: float, pct: float, color: str,
               track_color: str | None = None,
               thickness: float = 0.018,
               label_size: float = 22,
               sub_label: str | None = None,
               sub_label_size: float = 10) -> None:
    """
    Circular percentage donut rendered on its own compensated-aspect axes.
    cx/cy/radius are in figure-fraction units; sub_label renders below the
    donut at the figure level so it doesn't crowd the percent.
    """
    track = track_color or COLORS["border"]
    fig_w_in, fig_h_in = fig.get_size_inches()
    ratio = fig_w_in / fig_h_in          # < 1 on portrait
    # Axes box in figure fractions: width 2*rx, height 2*ry where ry = rx*ratio
    # so that the box is visually square (since fig is taller than wide).
    rx = radius
    ry = radius * ratio
    thickness_rel = max(0.001, min(0.5, thickness / max(rx, 1e-6)))

    ax = fig.add_axes([cx - rx, cy - ry, 2 * rx, 2 * ry], zorder=4)
    ax.set_xlim(-1, 1)
    ax.set_ylim(-1, 1)
    ax.set_aspect("equal")
    ax.set_axis_off()
    ax.set_facecolor("none")

    ax.add_patch(mpatches.Wedge(
        (0, 0), 1.0, 0, 360, width=thickness_rel,
        facecolor=track, edgecolor="none", linewidth=0,
    ))

    # Render the arc faithfully — no min-arc inflation — so the drawn sweep
    # always matches the displayed percentage. The thick ring already keeps
    # small slices (≥ 0.5 %) visible without needing to "round up".
    frac = max(0.0, min(1.0, pct / 100.0))
    if frac > 0.0005:
        theta1 = 90 - 360 * frac
        theta2 = 90
        ax.add_patch(mpatches.Wedge(
            (0, 0), 1.0, theta1, theta2,
            width=thickness_rel,
            facecolor=color, edgecolor="none", linewidth=0,
        ))

    pct_txt = f"{pct:.1f}%" if (pct > 0 and pct < 10) else f"{pct:.0f}%"
    ax.text(0, 0.0, pct_txt,
            ha="center", va="center",
            color=COLORS["text"], fontsize=label_size,
            fontweight="900", fontfamily=_FONT)

    if sub_label:
        fig.text(cx, cy - ry - 0.008, sub_label,
                 ha="center", va="top",
                 color=COLORS["text_muted"], fontsize=sub_label_size,
                 fontweight="bold", fontfamily=_FONT,
                 transform=fig.transFigure, zorder=5)


# ── Outcome check/X badge (drawn in its own axes, guaranteed circular) ───────

def _outcome_badge(fig: plt.Figure, cx: float, cy: float,
                   radius: float, is_pass: bool) -> None:
    """Small filled circle with a white check or X, drawn in a mini axes."""
    fig_w_in, fig_h_in = fig.get_size_inches()
    ratio = fig_w_in / fig_h_in
    rx = radius
    ry = radius * ratio

    ax = fig.add_axes([cx - rx, cy - ry, 2 * rx, 2 * ry], zorder=5)
    ax.set_xlim(-1, 1)
    ax.set_ylim(-1, 1)
    ax.set_aspect("equal")
    ax.set_axis_off()
    ax.set_facecolor("none")

    fill = COLORS["correct"] if is_pass else COLORS["missed"]
    ax.add_patch(mpatches.Circle(
        (0, 0), 1.0, facecolor=fill, edgecolor="none", linewidth=0,
    ))

    if is_pass:
        ax.plot([-0.45, -0.12, 0.48], [-0.02, -0.42, 0.38],
                color="white", linewidth=3.2,
                solid_capstyle="round", solid_joinstyle="round",
                zorder=6)
    else:
        ax.plot([-0.38, 0.38], [-0.38, 0.38],
                color="white", linewidth=3.2,
                solid_capstyle="round", zorder=6)
        ax.plot([-0.38, 0.38], [0.38, -0.38],
                color="white", linewidth=3.2,
                solid_capstyle="round", zorder=6)


def _surface_card(fig: plt.Figure, x: float, y: float, w: float, h: float,
                  radius: float = 0.012) -> None:
    """Rounded 'surface' card with a subtle interior border stroke."""
    fig.add_artist(mpatches.FancyBboxPatch(
        (x, y), w, h,
        boxstyle=f"round,pad=0,rounding_size={radius}",
        facecolor=COLORS["surface"],
        edgecolor=COLORS["border"], linewidth=0.8,
        transform=fig.transFigure, zorder=2,
    ))


# ── UMPIRE stat card ──────────────────────────────────────────────────────────

def _draw_umpire_block(fig: plt.Figure, ua: dict, y_top: float) -> float:
    """
    Umpire accuracy card with a big percent, name, accuracy bar, and
    miss/favor badges. Returns the y-coordinate where drawing ended.
    """
    ump_name = ua.get("name", "")
    ump_tot  = int(ua.get("total_called", 0) or 0)
    ump_cor  = int(ua.get("correct", 0) or 0)
    ump_pct  = ua.get("accuracy_pct")
    ws       = int(ua.get("wrong_strikes", 0) or 0)
    wb       = int(ua.get("wrong_balls", 0) or 0)
    favor    = ua.get("favor_score")

    has_data = bool(ump_name) or (ump_tot >= 5 and ump_pct is not None)
    if not has_data:
        return y_top

    x     = 0.06
    w     = 0.88
    h     = 0.092
    y_bot = y_top - h
    _surface_card(fig, x, y_bot, w, h)

    # Header row (left: UMPIRE label · right: umpire name)
    _sec_header(fig, "UMPIRE", y_top - 0.013, x=x + 0.028, size=11)
    if ump_name:
        fig.text(x + w - 0.028, y_top - 0.013, ump_name,
                 ha="right", va="center",
                 color=COLORS["text"], fontsize=12, fontweight="bold",
                 fontfamily=_FONT, transform=fig.transFigure, zorder=5)

    # Accuracy hero number + calibration caption (no bar — the big % plus the
    # "league avg" tail tells the whole story without visual noise).
    league_avg = 92.0
    if ump_pct is not None:
        fig.text(x + 0.032, y_top - 0.046, f"{ump_pct:.0f}%",
                 ha="left", va="center",
                 color=COLORS["text"], fontsize=38, fontweight="900",
                 fontfamily=_FONT, transform=fig.transFigure, zorder=5)
        fig.text(x + 0.032, y_top - 0.075,
                 f"{ump_cor} / {ump_tot} called pitches correct   ·   "
                 f"league avg {league_avg:.0f}%",
                 ha="left", va="center",
                 color=COLORS["text_muted"], fontsize=9.5,
                 fontfamily=_FONT, transform=fig.transFigure, zorder=5)

    # Right-side miss / favor badges — right-aligned with colored dots
    def _favor_color(f: int) -> str:
        # Small biases (≤2 extra calls) are essentially noise → neutral gray
        if abs(f) <= 2:
            return COLORS["neutral"]
        return COLORS["missed"] if f > 0 else COLORS["correct"]

    badges: list[tuple[str, str]] = []
    if ws:
        badges.append((f"{ws} wrong strike{'s' if ws != 1 else ''}",
                       COLORS["missed"]))
    if wb:
        badges.append((f"{wb} wrong ball{'s' if wb != 1 else ''}",
                       COLORS["accent"]))
    if favor is not None and favor != 0:
        label_txt = (f"+{favor} pitcher favor" if favor > 0
                     else f"{favor} batter favor")
        badges.append((label_txt, _favor_color(favor)))

    if badges:
        bx = x + w - 0.032
        by = y_top - 0.046
        for text, color in badges:
            fig.text(bx, by, text,
                     ha="right", va="center",
                     color=color, fontsize=10.5, fontweight="bold",
                     fontfamily=_FONT, transform=fig.transFigure, zorder=5)
            fig.add_artist(mpatches.Circle(
                (bx - _text_width_fig(text, 10.5) - 0.006, by),
                radius=0.0040, color=color, transform=fig.transFigure,
                zorder=5,
            ))
            by -= 0.020

    return y_bot


def _text_width_fig(s: str, fontsize: float) -> float:
    """Rough estimate of rendered width in figure fractions (for alignment)."""
    # Average glyph width ≈ 0.55 × font height. Font height in figure fractions:
    # fontsize(pt) × (1/72) in  ÷  fig_height_in. We don't have fig easily here;
    # callers use the portrait card, so height = CARD_H = 12 in.
    return 0.55 * fontsize * (1.0 / 72.0) / CARD_W * len(s) * 0.95


# ── GAME RATES: two rate donuts + replay summary ─────────────────────────────

def _draw_game_rates_block(fig: plt.Figure, summary: dict,
                           mgr_ch: list, y_top: float) -> float:
    """Game rates card with two circular gauges and optional replay summary."""
    ch_rate    = summary.get("challenge_rate", 0) or 0
    ot_rate    = summary.get("overturn_rate", 0) or 0
    total_abs  = summary.get("total_challenges", 0) or 0
    overturned = summary.get("overturned", 0) or 0

    x     = 0.06
    w     = 0.88
    h     = 0.118
    y_bot = y_top - h
    _surface_card(fig, x, y_bot, w, h)

    _sec_header(fig, "GAME RATES", y_top - 0.013, x=x + 0.028, size=11)

    # Donuts: ring is ~22 % of radius so the inner hole comfortably clears the
    # percentage text at label_size=18. Outer radius stays the same.
    radius      = 0.045
    donut_cy    = y_bot + 0.060
    donut_thick = 0.0100

    _pct_donut(fig,
               cx=x + w * 0.28, cy=donut_cy, radius=radius,
               pct=ch_rate, color=COLORS["accent"],
               thickness=donut_thick, label_size=17,
               sub_label="Challenge rate", sub_label_size=10)

    ot_color = (COLORS["correct"] if ot_rate >= 55 else
                COLORS["highlight"] if ot_rate >= 35 else
                COLORS["neutral"])
    ot_sub = (f"Overturn rate  ({overturned}/{total_abs})"
              if total_abs > 0 else "Overturn rate")
    _pct_donut(fig,
               cx=x + w * 0.72, cy=donut_cy, radius=radius,
               pct=ot_rate, color=ot_color,
               thickness=donut_thick, label_size=17,
               sub_label=ot_sub, sub_label_size=10)

    if mgr_ch:
        mgr_over = sum(1 for c in mgr_ch if c.get("outcome") == CORRECT_OVERTURN)
        fig.text(x + w - 0.028, y_top - 0.013,
                 f"Replay: {len(mgr_ch)} total · {mgr_over} overturned",
                 ha="right", va="center",
                 color=COLORS["text_muted"], fontsize=9,
                 fontweight="bold", fontfamily=_FONT,
                 transform=fig.transFigure, zorder=5)

    return y_bot


# ── ABS CHALLENGES list ──────────────────────────────────────────────────────

def _draw_abs_challenges(fig: plt.Figure,
                         abs_ch: list[dict],
                         y_top: float,
                         y_bottom: float) -> float:
    """Challenge list with colored dots, details, and outcome badges."""
    if not abs_ch:
        return y_top

    # Most egregious first: largest |edge_dist|, then inning order.
    def _sort_key(c):
        ed = c.get("edge_dist")
        mag = -abs(ed) if ed is not None else 0.0
        inn = c.get("inning") or 0
        half_order = 0 if c.get("half_inning") == "top" else 1
        return (mag, inn, half_order)

    sorted_ch = sorted(abs_ch, key=_sort_key)

    # Header
    header_y = y_top - 0.008
    _sec_header(fig, "ABS CHALLENGES", header_y, x=0.08, size=11)
    list_top = header_y - 0.024
    avail    = list_top - y_bottom

    # Layout: each row is one challenge. Allocate a row height based on
    # available space and the capped count.
    n_total = len(sorted_ch)
    n_show  = min(n_total, MAX_CHALLENGES_ON_CARD)

    # Each row fits a 12-pt primary line + 9.5-pt secondary + dividing rule;
    # keep a floor tall enough that the two lines never touch.
    MIN_ROW_H    = 0.048
    MAX_ROW_H    = 0.064
    SUMMARY_LINE = 0.024

    while n_show > 0:
        need = n_show * MIN_ROW_H + (SUMMARY_LINE if n_show < n_total else 0)
        if need <= avail:
            break
        n_show -= 1
    remainder = n_total - n_show

    if n_show == 0:
        if remainder:
            fig.text(0.08, list_top, f"{remainder} challenges",
                     ha="left", va="top",
                     color=COLORS["text_muted"], fontsize=10,
                     fontfamily=_FONT, transform=fig.transFigure, zorder=5)
        return y_bottom

    usable = avail - (SUMMARY_LINE if remainder else 0)
    row_h  = max(MIN_ROW_H, min(MAX_ROW_H, usable / n_show))

    x_left  = 0.08
    x_right = 0.92
    y = list_top

    for idx, ch in enumerate(sorted_ch[:n_show]):
        outcome  = ch.get("outcome")
        color    = OUTCOME_COLOR.get(outcome, COLORS["neutral"])
        label    = OUTCOME_LABEL.get(outcome, "—")
        half     = "T" if ch.get("half_inning") == "top" else "B"
        inn      = ch.get("inning", "?")
        pitcher  = _last(ch.get("pitcher"))
        batter   = _last(ch.get("batter"))
        cnt      = ch.get("count") or {}
        b_, s_   = cnt.get("balls"), cnt.get("strikes")
        cnt_str  = f" {b_}-{s_}" if b_ is not None else ""
        edge_d   = ch.get("edge_dist")
        orig     = (ch.get("original_call") or "").lower()
        call_lbl = "CS" if "called strike" in orig else "Ball"
        # Runners-on indicator: empty string for 0 runners (was showing "—"
        # which looked like a data bug in the rendered card).
        runners  = ch.get("runners_on")
        runner_s = ""
        if runners is not None and int(runners) > 0:
            runner_s = ["1on", "2on", "LOB"][min(int(runners) - 1, 2)]
        dist = ""
        if edge_d is not None:
            dist = f"  {abs(edge_d) * 12:.1f}\" {'in' if edge_d > 0 else 'out'}"

        # Row vertical centre
        y_row = y - row_h / 2

        # Zebra stripe on alternating rows for improved scanning
        if idx % 2 == 0:
            fig.add_artist(mpatches.Rectangle(
                (x_left - 0.008, y - row_h + 0.002),
                (x_right - x_left) + 0.016, row_h - 0.004,
                facecolor=COLORS["surface"], edgecolor="none", alpha=0.45,
                transform=fig.transFigure, zorder=2,
            ))

        # Coloured dot (left)
        fig.add_artist(mpatches.Circle(
            (x_left + 0.005, y_row), radius=0.006,
            color=color, transform=fig.transFigure, zorder=5,
        ))

        # Primary line: inning + count + matchup
        fig.text(x_left + 0.028, y_row + 0.010,
                 f"{half}{inn}{cnt_str}   {pitcher} vs {batter}",
                 ha="left", va="center",
                 color=COLORS["text"], fontsize=12, fontweight="bold",
                 fontfamily=_FONT, transform=fig.transFigure, zorder=5)

        # Secondary line: call type, result, distance, runners
        runner_part = f"   {runner_s}" if runner_s else ""
        fig.text(x_left + 0.028, y_row - 0.013,
                 f"{call_lbl}   ·   {label}{dist}{runner_part}",
                 ha="left", va="center",
                 color=color, fontsize=10, fontweight="bold",
                 fontfamily=_FONT, transform=fig.transFigure, zorder=5)

        # Outcome badge on right: green check for CORRECT_* outcomes,
        # red X for MISSED_CALL, gray for CORRECT_UPHELD, green for CORRECT_OVERTURN.
        is_pass = outcome in _PASS_OUTCOMES
        _outcome_badge(fig, cx=x_right - 0.018, cy=y_row,
                       radius=0.012, is_pass=is_pass)

        # Row separator
        fig.add_artist(mpatches.Rectangle(
            (x_left, y - row_h + 0.001), x_right - x_left, 0.0008,
            facecolor=COLORS["border"], edgecolor="none",
            transform=fig.transFigure, zorder=3,
        ))

        y -= row_h

    if remainder > 0:
        fig.text(x_left + 0.025, y - 0.010,
                 f"+ {remainder} more challenge{'s' if remainder != 1 else ''}",
                 ha="left", va="center",
                 color=COLORS["text_muted"], fontsize=9.5,
                 fontweight="bold", alpha=0.9,
                 fontfamily=_FONT, transform=fig.transFigure, zorder=5)

    return y_bottom


# ── Zone legend (placed directly beneath the strike-zone graphic) ───────────

def _legend_dot(fig: plt.Figure, cx: float, cy: float,
                color: str, rx: float = 0.0074) -> None:
    """
    Small filled circle icon — matches the umpire-error / correct-call dots in
    the zone plot. Uses Ellipse with an aspect-corrected y-radius so the icon
    appears physically round on a portrait (non-square) canvas.
    """
    ry = rx * _FIG_ASPECT
    fig.add_artist(mpatches.Ellipse(
        (cx, cy), width=2 * rx, height=2 * ry,
        facecolor=color, edgecolor="none",
        transform=fig.transFigure, zorder=6,
    ))


def _legend_target(fig: plt.Figure, cx: float, cy: float,
                   color: str, rx: float = 0.0110) -> None:
    """
    Ringed-circle icon — matches the ABS challenge markers in the zone plot
    (hollow ring + small centre dot). Aspect-corrected for portrait canvas.
    """
    ry      = rx * _FIG_ASPECT
    dot_rx  = rx * 0.33
    dot_ry  = dot_rx * _FIG_ASPECT
    lw_pts  = 3.0   # ring stroke width in points

    # Outer ring
    fig.add_artist(mpatches.Ellipse(
        (cx, cy), width=2 * rx, height=2 * ry,
        facecolor=COLORS["bg"], edgecolor=color, linewidth=lw_pts,
        transform=fig.transFigure, zorder=6,
    ))
    # Inner dot
    fig.add_artist(mpatches.Ellipse(
        (cx, cy), width=2 * dot_rx, height=2 * dot_ry,
        facecolor=color, edgecolor="none",
        transform=fig.transFigure, zorder=7,
    ))


def _draw_zone_legend(fig: plt.Figure, y_center: float) -> None:
    """
    Two-row legend whose icons exactly match the zone-plot markers:
      Row 1  — filled dots    (umpire wrong-call dots, inside the zone plot)
      Row 2  — ringed targets (ABS challenge ring+dot markers)
    Rows are independently centred so each row stays balanced.
    """
    # (draw_fn, color, label)
    row1: list[tuple] = [
        (_legend_dot,    COLORS["missed"],  "Wrong Strike"),
        (_legend_dot,    COLORS["accent"],  "Wrong Ball"),
    ]
    row2: list[tuple] = [
        (_legend_target, COLORS["correct"],  "ABS: Overturned"),
        (_legend_target, COLORS["neutral"],  "ABS: Upheld"),
        (_legend_target, COLORS["missed"],   "Missed Call"),
    ]

    row_gap = 0.030
    y_row1  = y_center + row_gap / 2
    y_row2  = y_center - row_gap / 2
    cell_w  = 0.30   # per-pill slot width (a touch wider for the larger text)

    for y, items in ((y_row1, row1), (y_row2, row2)):
        n       = len(items)
        total_w = n * cell_w
        x0      = (1.0 - total_w) / 2
        for i, (draw_fn, color, label) in enumerate(items):
            cx = x0 + i * cell_w + cell_w / 2
            draw_fn(fig, cx - 0.092, y, color)
            fig.text(cx - 0.074, y, label,
                     ha="left", va="center",
                     color=COLORS["text"], fontsize=12,
                     fontweight="bold", fontfamily=_FONT,
                     transform=fig.transFigure, zorder=5)


# ── Data source footer (single line pinned to bottom) ───────────────────────

def _draw_data_source(fig: plt.Figure, y: float = 0.028) -> None:
    """Hairline + centred data-source line."""
    fig.add_artist(mpatches.Rectangle(
        (0.10, y + 0.015), 0.80, 0.0008,
        transform=fig.transFigure,
        color=COLORS["border"], zorder=3,
    ))
    fig.text(0.500, y,
             "Data: MLB Stats API  +  Baseball Savant / Statcast",
             ha="center", va="center",
             color=COLORS["text_muted"], fontsize=9,
             fontweight="bold", fontfamily=_FONT,
             transform=fig.transFigure, zorder=5)


# ── Main card ─────────────────────────────────────────────────────────────────

def make_game_card(audit_result: dict, game_date: date,
                   game_pk: int | None = None) -> Path:
    """
    Portrait (9:16) ABS audit card on a cream background.
    Layout top → bottom: header · zone · UMPIRE card · GAME RATES card ·
                         ABS CHALLENGES list · footer legend + data source.
    """
    abs_ch  = audit_result.get("abs_challenges", []) or []
    ua      = audit_result.get("ump_accuracy", {}) or {}
    mgr_ch  = audit_result.get("manager_challenges", []) or []
    summary = audit_result.get("summary", {}) or {}

    plt.rcParams["font.family"] = _FONT
    fig = plt.figure(figsize=(CARD_W, CARD_H), dpi=CARD_DPI)
    fig.patch.set_facecolor(COLORS["bg"])

    # Vertical layout (figure-fraction y). Zone is the hero now; UMPIRE card
    # is shorter since the 94 % stat dropped from 52pt → 38pt.
    #
    #   0.923 – 1.000   header              (0.077)
    #   0.585 – 0.913   strike-zone plot    (0.328)   ← enlarged
    #   0.508 – 0.570   zone legend pills   (0.062)
    #   0.392 – 0.492   UMPIRE card         (0.100)
    #   0.255 – 0.380   GAME RATES card     (0.125)
    #   0.060 – 0.238   ABS CHALLENGES list (0.178, dynamic)
    #   0.028          data-source footer   (hairline at 0.043)

    # Header
    _draw_header(fig, audit_result, game_date)

    # Strike zone — wider axes so the zone reads as the hero element.
    zone_ax = fig.add_axes([0.06, 0.585, 0.88, 0.328])
    zone_ax.set_facecolor(COLORS["bg"])
    _draw_zone(zone_ax, abs_ch, ua)

    # Zone legend — directly beneath the strike-zone graphic.
    _draw_zone_legend(fig, y_center=0.539)

    # UMPIRE card (shown only when umpire data is present)
    has_ump = bool(ua.get("name") or (ua.get("total_called", 0) >= 5
                                       and ua.get("accuracy_pct") is not None))
    if has_ump:
        ump_bot = _draw_umpire_block(fig, ua, y_top=0.492)
        rates_top = ump_bot - 0.016
    else:
        rates_top = 0.492

    # GAME RATES card
    rates_bot = _draw_game_rates_block(fig, summary, mgr_ch, y_top=rates_top)

    # ABS CHALLENGES list — dynamic, filling space down to the footer
    footer_top  = 0.056
    list_top    = rates_bot - 0.016
    _draw_abs_challenges(fig, abs_ch, y_top=list_top, y_bottom=footer_top)

    # Data-source footer (pinned at the bottom)
    _draw_data_source(fig, y=0.028)

    # ── Save ─────────────────────────────────────────────────────────────────
    pk_suffix = f"_{game_pk}" if game_pk else ""
    out_path  = OUTPUT_DIR / f"game_card_{game_date.isoformat()}{pk_suffix}.png"
    plt.savefig(out_path, dpi=CARD_DPI,
                facecolor=COLORS["bg"],
                metadata={"Software": "ABS Auditor"},
                pil_kwargs={"compress_level": 1})
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
