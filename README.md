# ABS Auditor

Tracks MLB Automated Ball-Strike (ABS) challenges and manager replay challenges, generates visual audit cards, and posts them daily to X (Twitter).

## What it does

Every morning the GitHub Actions workflow:
1. Pulls yesterday's game schedule from the MLB Stats API
2. Pulls play-by-play data per game, extracting all challenge events
3. Cross-references pitch locations from Baseball Savant Statcast data
4. Scores each challenge (correct overturn / missed call / correctly upheld)
5. Generates a 1200×675 dark-mode audit card image (and a leaderboard on Mondays)
6. Posts a 2-3 tweet thread to X
7. Updates and commits `data/season_stats.json` back to the repo

---

## Setup

### 1. Clone and install

```bash
git clone https://github.com/YOUR_USERNAME/abs-auditor.git
cd abs-auditor
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env and fill in your Twitter credentials
```

### 3. Test run (dry-run — no tweets posted)

```bash
python main.py
# Runs for yesterday, logs everything, saves images to output/, does NOT post
```

```bash
python main.py --date 2025-04-10
# Same, for a specific date
```

### 4. Live post

```bash
python main.py --date 2025-04-10 --post
# Runs the full pipeline AND posts to X
```

---

## Twitter / X API credentials

You need **OAuth 1.0a** credentials to upload media (images) via the v1.1 API.

### Which tier do you need?

| Tier | Cost | Works? |
|------|------|--------|
| Free | $0 | Read-only; cannot post with media |
| **Basic** | **$100/month** | ✅ Full read/write with media upload |
| Pro | $5,000/month | Yes (overkill) |

**Alternative:** Apply for free "Elevated" access on the old v1.1 portal at [developer.twitter.com](https://developer.twitter.com/en/portal/products/elevated). As of 2025 this is granted case-by-case for non-commercial academic/hobby projects. If approved you get v1.1 media upload without paying for Basic.

### Steps

1. Go to [developer.twitter.com](https://developer.twitter.com) → create a project + app
2. Under **User authentication settings**: enable OAuth 1.0a with Read and Write permissions
3. Generate **API Key & Secret** and **Access Token & Secret** (make sure the access token is generated with Read+Write scope)
4. Copy the four values into your `.env`

---

## GitHub Actions setup

1. Push this repo to GitHub
2. Go to **Settings → Secrets and variables → Actions**
3. Add four repository secrets:
   - `TWITTER_API_KEY`
   - `TWITTER_API_SECRET`
   - `TWITTER_ACCESS_TOKEN`
   - `TWITTER_ACCESS_SECRET`
4. The workflow runs daily at 7 AM ET (`0 12 * * *` UTC)
5. Manually trigger via **Actions → ABS Auditor — daily run → Run workflow**

The workflow commits `data/season_stats.json` back after each run so season totals persist across runs.

---

## Backfill historical data

Rebuild `season_stats.json` from historical game data:

```bash
# Specific range
python backfill.py --start 2025-04-01 --end 2025-04-10

# From a start date through yesterday
python backfill.py --start 2025-04-01

# Slower requests to be polite to the API
python backfill.py --start 2025-04-01 --end 2025-04-30 --delay 3
```

---

## Changing the focus team

The "focus team" gets a highlighted border in the audit card and gets its own tweet in the thread.

**Option A: environment variable (temporary)**
```bash
FOCUS_TEAM=BOS python main.py --date 2025-04-10
```

**Option B: `.env` file (persistent for local runs)**
```
FOCUS_TEAM=LAD
ACCOUNT_HANDLE=@DodgersAudit
```

**Option C: GitHub Actions secret** — add `FOCUS_TEAM` as a repo secret and reference it in `daily.yml` under the `env:` block.

Team abbreviations follow the MLB Stats API standard (NYY, BOS, LAD, etc.).

---

## Project structure

```
abs-auditor/
├── .github/workflows/daily.yml   # GitHub Actions cron job
├── data/                         # local cache — gitignored except season_stats.json
├── output/                       # generated images — gitignored
├── src/
│   ├── config.py                 # constants, thresholds, colors
│   ├── fetch.py                  # MLB Stats API + Baseball Savant pulls
│   ├── audit.py                  # challenge scoring + season stats persistence
│   ├── viz.py                    # matplotlib card generation
│   └── post.py                   # Tweepy thread posting
├── main.py                       # pipeline orchestrator
├── backfill.py                   # historical data rebuild
├── requirements.txt
└── .env.example
```

---

## A note on ABS challenge detection

The `challengeType: "absChallenge"` field in the MLB play-by-play API was added during the 2024-25 ABS rollout. Coverage is expanding each season. The fetcher uses a two-layer approach:

1. **Primary:** look for `challengeType == "absChallenge"` at the play level
2. **Fallback:** scan `playEvents` for events of `type == "challenge"` and infer ABS vs manager based on whether pitch coordinate data is attached

To inspect a raw API response for a specific game:

```bash
# Find a gamePk first
curl "https://statsapi.mlb.com/api/v1/schedule?sportId=1&date=2025-04-10" | python -m json.tool | grep gamePk

# Then inspect play-by-play
curl "https://statsapi.mlb.com/api/v1/game/745567/playByPlay" | python -m json.tool | grep -A5 challenge
```

---

## Troubleshooting

| Symptom | Likely cause |
|---------|-------------|
| `No data for YYYY-MM-DD` | Off-day or Savant data not yet published (usually available by 10 AM ET) |
| `Missing Twitter credential env var` | `.env` not loaded or GitHub secret not set |
| Images saved but no tweet | `--post` flag not passed, or Tweepy auth error (check logs) |
| `season_stats.json` not committed | GitHub Actions needs `permissions: contents: write` (already set in `daily.yml`) |
