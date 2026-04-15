"""
ABS Auditor — configuration constants.
All user-configurable values live here.
"""
import os

# ── Identity ─────────────────────────────────────────────────────────────────
ACCOUNT_HANDLE = os.getenv("ACCOUNT_HANDLE", "@YankeesAudit")
FOCUS_TEAM     = os.getenv("FOCUS_TEAM", "NYY")

# ── Timezone ──────────────────────────────────────────────────────────────────
TIMEZONE = "America/New_York"

# ── Strike zone geometry ──────────────────────────────────────────────────────
# Plate is 17 inches wide → ±8.5 in → ±0.7083 ft from centre
ZONE_HALF_WIDTH_FT = 0.7083
ZONE_WIDTH_FT      = ZONE_HALF_WIDTH_FT * 2   # 1.4167 ft total

# ── Visualization ─────────────────────────────────────────────────────────────
MAX_CHALLENGES_ON_CARD = 6
FIGURE_WIDTH_PX  = 1200
FIGURE_HEIGHT_PX = 675
DPI              = 100   # 1200×675 @ 100 dpi

COLORS = {
    "bg":           "#0d1117",
    "surface":      "#161b22",
    "border":       "#30363d",
    "text":         "#e6edf3",
    "text_muted":   "#8b949e",
    "correct":      "#238636",   # green  — correct overturn
    "missed":       "#da3633",   # red    — incorrectly upheld
    "neutral":      "#6e7681",   # gray   — correctly upheld
    "highlight":    "#C4A44A",   # gold   — Yankees / focus team highlight
    "yankees_navy": "#003087",
    "zone_fill":    "#1c2128",
    "zone_edge":    "#30363d",
}

# ── Data paths ────────────────────────────────────────────────────────────────
import pathlib

ROOT_DIR        = pathlib.Path(__file__).parent.parent
DATA_DIR        = ROOT_DIR / "data"
OUTPUT_DIR      = ROOT_DIR / "output"
SEASON_STATS    = DATA_DIR / "season_stats.json"
ERROR_LOG       = DATA_DIR / "error_log.txt"

DATA_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

# ── API endpoints ─────────────────────────────────────────────────────────────
MLB_API_BASE    = "https://statsapi.mlb.com/api/v1"
SAVANT_CSV_URL  = "https://baseballsavant.mlb.com/statcast_search/csv"

# ── Retry config ──────────────────────────────────────────────────────────────
MAX_RETRIES     = 3
RETRY_BACKOFF_S = 10

# ── MLB team colour map (abbreviated) ────────────────────────────────────────
TEAM_COLORS = {
    "NYY": "#003087",
    "BOS": "#BD3039",
    "TOR": "#134A8E",
    "BAL": "#DF4601",
    "TBR": "#092C5C",
    "HOU": "#002D62",
    "TEX": "#003278",
    "LAA": "#BA0021",
    "OAK": "#003831",
    "SEA": "#0C2C56",
    "CLE": "#00385D",
    "MIN": "#002B5C",
    "CWS": "#27251F",
    "KCR": "#004687",
    "DET": "#0C2340",
    "NYM": "#002D72",
    "PHI": "#E81828",
    "ATL": "#CE1141",
    "MIA": "#00A3E0",
    "WSN": "#AB0003",
    "CHC": "#0E3386",
    "STL": "#C41E3A",
    "MIL": "#FFC52F",
    "CIN": "#C6011F",
    "PIT": "#FDB827",
    "LAD": "#005A9C",
    "SFG": "#FD5A1E",
    "ARI": "#A71930",
    "COL": "#333366",
    "SDP": "#2F241D",
}
