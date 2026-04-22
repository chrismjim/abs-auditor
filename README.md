# ABS Auditor

Daily auditing tool for MLB's Automated Ball-Strike (ABS) Challenge System. For every MLB game, it pulls pitch-tracking data and challenge events, scores each challenge against the ground-truth strike zone, generates a portrait "game card" image, and posts it as a thread to X.

The card's job is to surface **what went wrong**: the umpire's incorrect ball/strike calls, the ABS challenges that followed, and their outcomes.

---

## Table of contents

1. [What the tool does](#what-the-tool-does)
2. [Quick start](#quick-start)
3. [Pipeline — end-to-end data flow](#pipeline--end-to-end-data-flow)
4. [The data model](#the-data-model)
5. [Challenge scoring](#challenge-scoring)
6. [The game card — visual grammar](#the-game-card--visual-grammar)
7. [Module reference](#module-reference)
8. [Twitter / X credentials](#twitter--x-credentials)
9. [GitHub Actions](#github-actions)
10. [Backfill historical data](#backfill-historical-data)
11. [Focus team configuration](#focus-team-configuration)
12. [Project layout](#project-layout)
13. [Troubleshooting](#troubleshooting)

---

## What the tool does

Every day the pipeline:

1. Pulls yesterday's MLB game schedule from the **MLB Stats API**.
2. For each game, reads play-by-play to extract every ABS challenge and every manager replay challenge.
3. Cross-references pitch coordinates (`plate_x`, `plate_z`, `sz_top`, `sz_bot`) from the **Baseball Savant Statcast CSV**.
4. Scores each ABS challenge against the **standard rulebook strike zone** (1.50 ft – 3.50 ft vertical, ±0.7083 ft horizontal).
5. Computes the umpire's called-pitch accuracy for the game and identifies every missed call.
6. Renders a **2160 × 3840 px portrait "game card"** showing the strike zone, the umpire's wrong calls, and each ABS challenge in context.
7. Posts a 1–3 tweet thread per finished game (live mode) or one thread for the whole day (batch mode).
8. Persists season-long team/umpire rollups in `data/season_stats.json`.

The card is the primary artefact. The pipeline optimises for **readability at a glance** — one image, one story.

---

## Quick start

```bash
# 1. Clone and install
git clone https://github.com/YOUR_USERNAME/abs-auditor.git
cd abs-auditor
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Configure
cp .env.example .env
# Edit .env with your Twitter creds

# 3. Dry-run — generates images, never tweets
python main.py                       # yesterday in ET
python main.py --date 2026-04-14     # specific date
python main.py --live                # today, per completed game
python main.py --leaderboard         # force a leaderboard image

# 4. Live post
python main.py --date 2026-04-14 --post
```

Generated images go to `output/`. Nothing is posted unless `--post` is passed.

---

## Pipeline — end-to-end data flow

```
                    ┌───────────────────────────┐
                    │  main.py                  │
                    │  argparse + logging       │
                    └─────────────┬─────────────┘
                                  │
             batch mode           │            live mode
           (default, one          │          (per-game, once
            thread/day)           │           each Final)
                                  │
           ┌──────────────────────┴──────────────────────┐
           ▼                                             ▼
     run_batch(date)                               run_live(date)
           │                                             │
           │          ┌──────────────────────────────────┴─────────┐
           │          ▼                                            ▼
           │     get_schedule()                               fetch_game(gamePk)
           ▼                                                       │
   ┌────────────────┐    ┌────────────────────┐    ┌───────────────┴───────────────┐
   │   fetch.py     │    │   Baseball Savant  │    │   play-by-play JSON          │
   │  fetch_day()   │───▶│   CSV (per-day)    │◀───│   /game/{pk}/playByPlay      │
   │  fetch_game()  │    │   plate_x / plate_z│    │   + umpire accuracy calc     │
   └────────┬───────┘    └────────────────────┘    └──────────────────────────────┘
            │
            ▼
   ┌────────────────┐
   │   audit.py     │
   │  score_abs_…   │  Adds in_zone / edge_dist / outcome to every challenge
   │  score_mgr_…   │  Aggregates team_stats, umpire_stats, storylines, summary
   │  audit_day()   │
   │  update_       │
   │  season_stats  │
   └────────┬───────┘
            │
            ▼
   ┌────────────────┐
   │   viz.py       │
   │  make_game_card│  Portrait card (2160×3840) — hero artefact
   │  make_         │  Landscape leaderboard / trend charts (Mondays)
   │  leaderboard   │
   │  generate_     │
   │  images()      │
   └────────┬───────┘
            │
            ▼
   ┌────────────────┐
   │   post.py      │
   │  post_thread   │  Tweepy OAuth 1.0a (v1.1 for media, v2 for text)
   └────────────────┘
```

---

## The data model

### Challenge record (after `fetch.py`)

Every challenge — ABS or manager replay — is a dict with these keys:

| Field | Type | Notes |
|---|---|---|
| `challenge_type` | `"absChallenge"` \| `"managerChallenge"` \| `"umpireReview"` | |
| `challenger` | `str` — team abbr or player | |
| `half_inning` | `"top"` \| `"bottom"` | |
| `inning` | `int` | |
| `count` | `{"balls": int, "strikes": int}` | ABS only |
| `pitch_x`, `pitch_z` | `float` (ft) | ABS only — plate location |
| `sz_top`, `sz_bot` | `float` (ft) | ABS only — per-batter vertical zone |
| `original_call` | `"called strike"` \| `"ball"` | ABS only |
| `overturned` | `bool` | |
| `pitcher`, `batter` | `str` | ABS only |
| `runners_on` | `int 0–3` | ABS only |
| `description` | `str` | full MLB-API description string |

After `audit.py`, ABS challenges gain:

| Added field | Value |
|---|---|
| `in_zone` | `True` / `False` / `None` |
| `edge_dist` | Signed distance in ft from nearest zone edge (`+` inside, `−` outside) |
| `outcome` | One of the outcome constants below |
| `outcome_uncertain` | `bool` — `True` if we lacked zone data |

### Umpire accuracy (emitted by `fetch.py`)

Computed over **every called pitch** in the game — not just challenged ones — against the standard rulebook zone:

```python
{
    "name":                "Tripp Gibson",
    "total_called":        158,      # total called strikes + balls
    "correct":             148,      # inside-zone strikes + outside-zone balls
    "incorrect":           10,
    "accuracy_pct":        93.7,
    "wrong_strikes":       10,       # called strike, outside zone
    "wrong_balls":         0,        # called ball, inside zone
    "favor_score":         10,       # wrong_strikes − wrong_balls (+ = pitcher-friendly)
    "wrong_strike_coords": [(0.35, 2.1), ...],   # (px, pz) in ft — OUTSIDE the zone
    "wrong_ball_coords":   [],                    # (px, pz) in ft — INSIDE the zone
}
```

These coord lists drive the red / amber dots in the zone plot.

---

## Challenge scoring

ABS outcomes (in `src/audit.py`):

| Constant | String | Meaning |
|---|---|---|
| `CORRECT_OVERTURN` | `"correct_overturn"` | ABS changed the call — call is now correct |
| `CORRECT_UPHELD` | `"correct_upheld"` | ABS agreed with the original call — call stood |
| `MISSED_CALL` | `"missed_call"` | Challenge denied, but the original call was still wrong by the zone — challenge should have been made but wasn't used |

### Why there is no "ABS was wrong" outcome

ABS (Hawk-Eye) **is the ground truth** in MLB's current implementation. The challenge system has only two official outcomes in the Stats API: **overturn** or **confirm**. If ABS says overturn, the call is overturned; if it confirms, the call stands. There is no authority above Hawk-Eye to declare ABS itself wrong, and the commissioner has [rejected any "call stands" buffer zone](https://baseballsavant.mlb.com/abs) for borderline pitches. A former `INCORRECT_OVERTURN` category is deliberately absent — any overturn is, by definition, correct per the system-of-record.

### Scoring algorithm (ABS)

```python
in_zone = pitch_in_zone(px, pz, sz_top, sz_bot)
original_correct = (original_was_strike and in_zone) or \
                   (original_was_ball   and not in_zone)

if overturned:                        outcome = CORRECT_OVERTURN
elif not overturned and original_correct: outcome = CORRECT_UPHELD
else:                                 outcome = MISSED_CALL   # not overturned, original was wrong
```

When `in_zone` cannot be determined (no coords), the challenge is marked `outcome_uncertain = True` and gets a best-effort label.

---

## The game card — visual grammar

Portrait 2160 × 3840 px (9:16 — Instagram / Twitter story size). Off-white theme. Rendered in `src/viz.py::make_game_card`.

```
┌────────────────────────────────────────┐
│  Accent strip — away | home team colors│
│  SF    ·   3 – 0   ·   CIN             │ header
│  ABS CHALLENGE AUDIT · APR 14, 2026    │
│  ──────────── (hairline) ──────────────│
│                                        │
│       ┌──────────────────┐             │
│       │  ·  ·  ·         │  strike     │
│       │   ○   ·  ·       │  zone       │
│       │  ·     ○   ·     │  (hero)     │
│       │       · ⬢        │             │
│       │        ○         │             │
│       └──────────────────┘             │
│         ⎯⎯⎯ (plate) ⎯⎯⎯                │
│                                        │
│   ● Wrong Strike     ● Wrong Ball      │ legend
│   ⬢ ABS: Overturned ⬢ Upheld ⬢ Missed  │
│  ┌─────────────────────────────────┐   │
│  │ UMPIRE          Tripp Gibson    │   │
│  │ 94%                             │   │
│  │ 148/158 · league avg 92%    ●10 │   │ ump card
│  │                              ●2 │   │
│  │                              +1 │   │
│  └─────────────────────────────────┘   │
│  ┌─────────────────────────────────┐   │
│  │ GAME RATES      Replay: 1 / 0   │   │
│  │   ⊙1.3%          ⊙33%           │   │ rates
│  │  Challenge rate Overturn rate   │   │
│  └─────────────────────────────────┘   │
│  ABS CHALLENGES                        │
│  ● T6 2-3  Burke vs Devers       ✓    │ list
│  ● T7 3-3  Gonzalez vs Smith     ✓    │
│  ● T6 2-3  Burns vs Bailey       ✗    │
│  ───────────────────────────────────   │
│  Data: MLB Stats API + Savant/Statcast │ footer
└────────────────────────────────────────┘
```

### Dot grammar (exactly what each marker means)

| Marker | Where | Meaning |
|---|---|---|
| **● red filled dot** | zone plot | Called strike that was **outside the zone** (wrong strike) |
| **● amber filled dot** | zone plot | Called ball that was **inside the zone** (wrong ball) |
| **⬢ green ringed target** | zone plot | ABS challenge — call was **correctly overturned** |
| **⬢ gray ringed target** | zone plot | ABS challenge — call was **upheld** (challenge failed, original was right) |
| **⬢ red ringed target** | zone plot | ABS challenge — **missed call** (challenge denied but original was wrong) |
| **✓ green badge** | list (right) | Challenge resulted in a "pass" outcome (`CORRECT_OVERTURN` or `CORRECT_UPHELD`) |
| **✗ red badge** | list (right) | Challenge resulted in `MISSED_CALL` |
| **Colored left dot** | list (left) | Same color as the ABS challenge marker in the zone plot |

The zone plot and the list are **linked by color and by label** (`T6 2-3` = "Top of 6th, 2-balls 3-strikes count"). A marker in the zone has the same color as its list-row dot.

### Donuts & bars

- **UMPIRE `94%`** — called-pitch accuracy for the plate umpire, computed over **every** called strike and called ball.
- **Challenge rate** — % of takes (non-swings) where a challenge was initiated.
- **Overturn rate** — % of challenges that resulted in an overturned call. Thick 22%-of-radius ring; the arc is rendered **faithfully** (no min-arc inflation) so it matches the number.

---

## Module reference

### `main.py` — orchestrator

Two modes:

| Mode | Trigger | Behaviour |
|---|---|---|
| **batch** | default | Runs once for a full date, posts one thread summarising the day |
| **live** | `--live` | Scans the day's schedule; processes each `Final` game whose `gamePk` is not in `data/posted_games.json` and posts a per-game thread |

Key CLI flags:

| Flag | Meaning |
|---|---|
| `--date YYYY-MM-DD` | Target date. Default: yesterday in ET (batch), today in ET (live) |
| `--post` | Actually post to X. Without this flag, everything runs but no tweets are sent |
| `--live` | Switch to live per-game mode |
| `--leaderboard` | Force-generate the season leaderboard image (runs automatically on Mondays) |

### `src/fetch.py` — data layer

- `get_schedule(date)` — `GET /schedule?sportId=1&date=…` → list of games
- `get_pitches(date)` — Baseball Savant CSV for the day, cached per-day in `data/`
- `fetch_game(gamePk, …)` — pulls play-by-play + Statcast for a single game → `(challenges, umpire_accuracy)`
- `fetch_day(date)` — loops over all games for the date
- `enrich_challenge_with_statcast(challenge, pitches_df)` — joins on `gamePk + atBatNumber + pitchNumber` to add `pitch_x / pitch_z / sz_top / sz_bot`
- `_compute_umpire_accuracy(playByPlay)` — iterates over every called strike + ball and populates the umpire accuracy dict (see [data model](#the-data-model))
- `get_abs_leaderboard(year)` — seasonal ABS challenge leaderboard CSV

**ABS-vs-manager disambiguation** — in 2026 the API no longer populates `about.challengeType`, so `fetch.py` parses `result.description` text: anything describing a "(pitch result)" is ABS; everything else (play-at-1st / tag / home run) is manager replay or umpire review.

### `src/audit.py` — scoring

- `score_abs_challenge(ch)` → adds `in_zone`, `edge_dist`, `outcome`
- `score_manager_challenge(ch)` → adds `outcome` based on `overturned` + subtype
- `audit_day(challenges, pitches_df, date)` → returns:
  ```python
  {
      "game_date":          "2026-04-14",
      "abs_challenges":     [...],
      "manager_challenges": [...],
      "team_stats":         {"SF": {...}, "CIN": {...}},
      "umpire_stats":       {"Tripp Gibson": {...}},
      "ump_accuracy":       {...},       # accuracy for the plate umpire
      "storylines":         ["Biggest miss: ...", ...],
      "summary": {
          "total_challenges": 3,
          "overturned":       1,
          "missed_calls":     1,
          "correct_upheld":   1,
          "challenge_rate":   1.3,
          "overturn_rate":    33.3,
      },
  }
  ```
- `update_season_stats(audit_result)` → merges today's totals into `data/season_stats.json`
- `load_season_stats()` → reads the same file

### `src/viz.py` — rendering

Portrait card entry point: **`make_game_card(audit_result, game_date, game_pk=None)`** → saves PNG to `output/game_card_<date>_<pk>.png`.

Internal pipeline:

```
_draw_header(fig, audit, date)         → team-colour accent + score + date subtitle
_draw_zone(ax, abs_ch, ua)             → strike zone + plate + grid + ump dots + ABS markers
_draw_zone_legend(fig, y_center)       → two-row pill legend beneath the zone
_draw_umpire_block(fig, ua, y_top)     → rounded card with 94% + league-avg + miss/favor badges
_draw_game_rates_block(fig, summary,   → rounded card with two faithful donuts
                       mgr_ch, y_top)
_draw_abs_challenges(fig, abs_ch,      → per-challenge rows w/ zebra stripe + outcome badge
                     y_top, y_bottom)
_draw_data_source(fig, y)              → hairline + footer text
```

Helpers worth knowing:

| Helper | Purpose |
|---|---|
| `_setup_font()` | Prefers Apple SF Pro (SFNS.ttf, registered as `"System Font"` on macOS); falls back to Inter → Roboto → Helvetica Neue → sans-serif |
| `_pct_donut(...)` | Circular percentage donut on its own aspect-corrected mini-axes. Renders arc faithfully to the value |
| `_outcome_badge(...)` | Green ✓ / red ✗ badge drawn with `Line2D` segments (not glyphs) so font availability doesn't matter |
| `_legend_dot` / `_legend_target` | Legend icons that match the zone-plot markers 1:1 |
| `_surface_card(...)` | Rounded off-white panel with a hairline border stroke |

Also in this module:

- `make_leaderboard(rows)` → landscape chart used on Mondays
- `make_trend_chart(history)` → season-to-date trend
- `generate_images(audit_result, season_stats, date, …)` → the dispatcher `main.py` actually calls

### `src/post.py` — Tweepy thread posting

- `post_thread(audit_result, images, game_date, dry_run=False)` → uploads images via v1.1, composes tweet text, posts via v2
- `post_error_tweet(msg, dry_run=…)` → safety-net alert on pipeline failure

### `src/config.py` — constants

All user-configurable values live here:

| Constant | Purpose |
|---|---|
| `TIMEZONE = "America/New_York"` | Used for "yesterday"/"today" resolution |
| `ZONE_HALF_WIDTH_FT`, `ZONE_TOP_FT`, `ZONE_BOT_FT` | Standard rulebook zone — **used for scoring AND for the visualization** so the card never lies about where a pitch was relative to the zone |
| `CARD_WIDTH_PX / CARD_HEIGHT_PX / CARD_DPI` | Portrait card dimensions (2160 × 3840 @ 320 DPI) |
| `COLORS` | Off-white theme palette — every color on the card is one of these |
| `TEAM_COLORS` | Primary brand hex for every MLB team |
| `MAX_CHALLENGES_ON_CARD` | Hard cap on list rows (overflow → "+ N more challenges") |

### `backfill.py` — historical rebuild

Walks a date range, calls `fetch_day` + `audit_day` + `update_season_stats` in sequence. Used to rebuild `season_stats.json` from scratch or to catch up after downtime.

---

## Twitter / X credentials

Media (image) upload requires **OAuth 1.0a v1.1** — text posting uses v2.

| Tier | Cost | Works? |
|---|---|---|
| Free | $0 | Read-only; cannot post with media |
| **Basic** | **$100/month** | ✅ Full read/write with media upload |
| Pro | $5,000/month | Yes (overkill) |

**Alternative:** Apply for free "Elevated" access on [developer.twitter.com](https://developer.twitter.com/en/portal/products/elevated). As of 2025 this is granted case-by-case for non-commercial academic/hobby projects.

### Setup

1. Create a project + app at [developer.twitter.com](https://developer.twitter.com)
2. Under **User authentication settings**: enable OAuth 1.0a with **Read and Write** permissions
3. Generate **API Key & Secret** and **Access Token & Secret** (make sure the access token is generated *after* setting Read+Write)
4. Copy the four values into your `.env`:
   ```
   TWITTER_API_KEY=...
   TWITTER_API_SECRET=...
   TWITTER_ACCESS_TOKEN=...
   TWITTER_ACCESS_SECRET=...
   ```

---

## GitHub Actions

1. Push to GitHub
2. **Settings → Secrets and variables → Actions** → add four secrets:
   - `TWITTER_API_KEY`, `TWITTER_API_SECRET`, `TWITTER_ACCESS_TOKEN`, `TWITTER_ACCESS_SECRET`
3. The workflow at `.github/workflows/daily.yml` runs at 7 AM ET (`0 12 * * *` UTC)
4. Manual trigger via **Actions → ABS Auditor — daily run → Run workflow**
5. After each run the workflow commits `data/season_stats.json` back so season totals persist

---

## Backfill historical data

```bash
# Specific range
python backfill.py --start 2025-04-01 --end 2025-04-10

# From a start date through yesterday
python backfill.py --start 2025-04-01

# Slower requests (be polite to the API)
python backfill.py --start 2025-04-01 --end 2025-04-30 --delay 3
```

---

## Focus team configuration

The "focus team" gets a highlighted border on the card and its own tweet in the thread.

**Option A — environment variable (temporary)**
```bash
FOCUS_TEAM=BOS python main.py --date 2026-04-14
```

**Option B — `.env` (persistent)**
```
FOCUS_TEAM=LAD
ACCOUNT_HANDLE=@DodgersAudit
```

**Option C — GitHub Actions secret** — add `FOCUS_TEAM` as a repo secret and reference in `daily.yml` under `env:`.

Team abbreviations follow the MLB Stats API standard (`NYY`, `BOS`, `LAD`, etc.).

---

## Project layout

```
abs-auditor/
├── .github/workflows/daily.yml   GitHub Actions cron + commit-back
├── data/                         Local cache — season_stats.json is committed
│   ├── season_stats.json         Season-long rollups (persisted)
│   ├── daily_history.json        Per-day history (persisted)
│   ├── posted_games.json         De-dup for live mode
│   └── error_log.txt             Append-only error log
├── output/                       Generated images — gitignored
├── src/
│   ├── config.py                 Constants, thresholds, color palette
│   ├── fetch.py                  MLB Stats API + Savant + pybaseball
│   ├── audit.py                  Scoring + season-stats persistence
│   ├── viz.py                    Matplotlib card + leaderboard + trend
│   └── post.py                   Tweepy thread posting
├── main.py                       Pipeline orchestrator
├── backfill.py                   Historical data rebuild
├── requirements.txt
└── .env.example
```

---

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `No data for YYYY-MM-DD` | Off-day or Savant data not yet published (usually available by 10 AM ET) |
| `Missing Twitter credential env var` | `.env` not loaded or GitHub secret not set |
| Images saved but no tweet | `--post` flag not passed, or Tweepy auth error (check logs) |
| `season_stats.json` not committed by Actions | Workflow needs `permissions: contents: write` (already set in `daily.yml`) |
| Challenge row's `outcome_uncertain: true` | Pitch had no Statcast coords — usually an old game before Savant coverage kicked in |
| Card legend missing colors | The scenario has zero of that outcome type in the game — expected |
| Fonts look wrong on Linux CI | Apple's SF Pro (`SFNS.ttf`) is only present on macOS. On Linux the font resolver falls back to Inter → Roboto → Helvetica → DejaVu. Install Inter in the workflow for consistency with macOS output |

### Inspecting raw API data

```bash
# Find a gamePk
curl "https://statsapi.mlb.com/api/v1/schedule?sportId=1&date=2026-04-14" \
  | python -m json.tool | grep gamePk

# Inspect challenges in a specific game
curl "https://statsapi.mlb.com/api/v1/game/745567/playByPlay" \
  | python -m json.tool | grep -A5 challenge
```
