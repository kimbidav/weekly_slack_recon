# Quick Start

## Launch the dashboard

Double-click **`Slack Reconciliation.app`** on the Desktop.

This opens the Pipeline Reconciliation Dashboard at `http://localhost:8001/dashboard.html`.

---

## Daily usage

1. **Sync Slack** — click "Sync Slack" to scan `candidatelabs-*` channels for new submissions (~1–2 min).
2. **Import Ashby** — click "Import Ashby" to pull in the latest Ashby export. Automatically reads the newest `.json` from `~/Desktop/Ashby automation/output/`.
3. **Review candidates** — filter by status, company/channel, or source. Click stage links to open Ashby directly.

---

## First-time setup

### 1. Install dependencies

```bash
cd /Users/david/Desktop/weekly_slack_recon
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Create `.env`

```env
SLACK_BOT_TOKEN=xoxp-...            # User OAuth Token from api.slack.com/apps
DK_EMAIL=dkimball@candidatelabs.com
LOOKBACK_DAYS=45
UNCLEAR_FOLLOWUP_DAYS=7
INACTIVITY_DAYS=5
ANTHROPIC_API_KEY=sk-ant-api03-...  # From console.anthropic.com
ASHBY_JSON_PATH=/Users/david/Desktop/Ashby automation/output
```

### 3. Run

```bash
python serve_dashboard.py
```

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| "Import Ashby" shows no file | Run the Ashby Automation tool first to generate a fresh export |
| Slack sync times out | Normal — Slack rate limits are slow. Wait for it to finish. |
| App won't open | `python serve_dashboard.py` from terminal to see error output |

See **README.md** for full documentation.
