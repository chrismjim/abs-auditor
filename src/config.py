"""
ABS Auditor — configuration constants.
All user-configurable values live here.
"""
import pathlib

# ── Timezone ──────────────────────────────────────────────────────────────────
TIMEZONE = "America/New_York"

# ── Strike zone geometry ──────────────────────────────────────────────────────
# Plate is 17 inches wide → ±8.5 in → ±0.7083 ft from centre
ZONE_HALF_WIDTH_FT = 0.7083
ZONE_WIDTH_FT      = ZONE_HALF_WIDTH_FT * 2   # 1.4167 ft total

# Standard MLB rulebook zone heights (used for accuracy calc AND visualization)
# Using fixed heights keeps the accuracy logic consistent with what's drawn.
ZONE_TOP_FT = 3.50
ZONE_BOT_FT = 1.50

# ── Visualization ─────────────────────────────────────────────────────────────
MAX_CHALLENGES_ON_CARD = 6
FIGURE_WIDTH_PX  = 2400
FIGURE_HEIGHT_PX = 1350
DPI              = 200   # 2400×1350 @ 200 dpi

COLORS = {
    "bg":         "#0d1117",
    "surface":    "#161b22",
    "border":     "#30363d",
    "text":       "#e6edf3",
    "text_muted": "#8b949e",
    "correct":    "#3fb950",   # bright green  — correct overturn
    "missed":     "#f85149",   # bright red    — missed call / wrong overturn
    "neutral":    "#848d97",   # gray          — correctly upheld
    "highlight":  "#e3b341",   # amber         — league average / accents
    "zone_fill":  "#1c2128",
    "zone_edge":  "#444c56",
}

# ── Data paths ────────────────────────────────────────────────────────────────
ROOT_DIR     = pathlib.Path(__file__).parent.parent
DATA_DIR     = ROOT_DIR / "data"
OUTPUT_DIR   = ROOT_DIR / "output"
SEASON_STATS  = DATA_DIR / "season_stats.json"
DAILY_HISTORY = DATA_DIR / "daily_history.json"
POSTED_GAMES  = DATA_DIR / "posted_games.json"
ERROR_LOG     = DATA_DIR / "error_log.txt"

DATA_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

# ── API endpoints ─────────────────────────────────────────────────────────────
MLB_API_BASE   = "https://statsapi.mlb.com/api/v1"
SAVANT_CSV_URL = "https://baseballsavant.mlb.com/statcast_search/csv"

# ── Retry config ──────────────────────────────────────────────────────────────
MAX_RETRIES     = 3
RETRY_BACKOFF_S = 10

# ── MLB team colour map (primary brand colour, hex) ───────────────────────────
TEAM_COLORS = {
    "NYY": "#003087", "BOS": "#BD3039", "TOR": "#134A8E",
    "BAL": "#DF4601", "TBR": "#092C5C", "TB":  "#092C5C",
    "HOU": "#002D62", "TEX": "#003278", "LAA": "#BA0021",
    "OAK": "#003831", "ATH": "#003831", "SEA": "#0C2C56",
    "CLE": "#00385D", "MIN": "#002B5C", "CWS": "#27251F",
    "KCR": "#004687", "KC":  "#004687", "DET": "#0C2340",
    "NYM": "#002D72", "PHI": "#E81828", "ATL": "#CE1141",
    "MIA": "#00A3E0", "WSN": "#AB0003", "WSH": "#AB0003",
    "CHC": "#0E3386", "STL": "#C41E3A", "MIL": "#FFC52F",
    "CIN": "#C6011F", "PIT": "#FDB827", "LAD": "#005A9C",
    "SFG": "#FD5A1E", "SF":  "#FD5A1E", "ARI": "#A71930",
    "COL": "#333366", "SDP": "#2F241D", "SD":  "#2F241D",
}
