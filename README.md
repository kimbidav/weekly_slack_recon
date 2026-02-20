## Pipeline Reconciliation Dashboard (DK View)

A single-pane-of-glass tool for tracking all active candidates — across both **Slack submissions** and **Ashby ATS** — in one interactive dashboard. Built for David Kimball at Candidate Labs.

---

## What it does

| Source | What it tracks |
|--------|---------------|
| **Slack** | DK's top-level messages in `candidatelabs-*` channels that contain a LinkedIn URL. Status inferred from emoji reactions and thread keywords. |
| **Ashby** | Candidates credited to DK in the Ashby ATS export. Pulled from a separate Ashby Automation tool (Node.js, lives at `~/Desktop/Ashby automation/`). |

The dashboard merges both sources and flags candidates that appear in both (LinkedIn URL cross-match).

---

## Daily workflow

1. **Open the dashboard** — double-click `Slack Reconciliation.app` on the Desktop.
2. **Sync Slack** — click the "Sync Slack" button to scan all `candidatelabs-*` channels for recent submissions (takes ~1–2 min due to rate limits).
3. **Import Ashby** — click "Import Ashby" to pull in the latest Ashby export from `~/Desktop/Ashby automation/output/` (auto-picks the newest `.json` file).
4. **Review the dashboard** — filter by status, channel/company, or source. Click stage links for Ashby candidates to jump straight to their Ashby page.

---

## Setup

### 1. Prerequisites

```bash
cd /Users/david/Desktop/weekly_slack_recon
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. `.env` file

Create `.env` in the project root:

```env
# Slack token (User OAuth Token recommended — no need to add bot to channels)
SLACK_BOT_TOKEN=xoxp-...

# DK's email (used to look up Slack user ID)
DK_EMAIL=dkimball@candidatelabs.com

# How far back to scan Slack for submissions
LOOKBACK_DAYS=45

# Thresholds for flagging follow-ups
UNCLEAR_FOLLOWUP_DAYS=7
INACTIVITY_DAYS=5

# Anthropic API key for AI enrichment
ANTHROPIC_API_KEY=sk-ant-api03-...

# Path to Ashby JSON export directory (or a specific file)
# The importer auto-picks the most recently modified .json in the directory
ASHBY_JSON_PATH=/Users/david/Desktop/Ashby automation/output
```

### 3. Slack app scopes

Create a Slack app at https://api.slack.com/apps with these **User Token Scopes**:
`channels:read`, `groups:read`, `channels:history`, `groups:history`, `users:read`, `users:read.email`, `reactions:read`, `chat:write`

Copy the `xoxp-...` User OAuth Token into `.env`.

---

## Ashby integration

The Ashby data comes from a separate **Ashby Automation** tool (`~/Desktop/Ashby automation/`) that extracts the pipeline via Ashby's internal GraphQL API using saved session cookies. Run that tool to generate a fresh JSON export, then click "Import Ashby" in the dashboard.

**What gets imported:**
- Only candidates where `creditedTo` is DK (`David`, `David Kimball`, `David CL`, `DK`)
- The `company_name` field shows the client org (`orgName` from Ashby — e.g., "Agave", "Canals")
- The Stage / Thread column shows the pipeline stage and links to `app.ashbyhq.com/candidates/{id}`

**To regenerate the Ashby export:**
```bash
cd ~/Desktop/Ashby\ automation
npm run extract   # or whatever the run command is — see that project's README
```

---

## Dashboard features

### Filters & search
- **Status filter**: CLOSED / IN PROCESS — explicit / IN PROCESS — unclear
- **Channel filter**: Slack channels (shown as clean names, e.g., "Matter Intelligence" instead of `#candidatelabs-matter-intelligence`)
- **Source filter**: All / Slack only / Ashby only
- **Search**: Searches candidate name, company name, and job title

### Table columns
| Column | Slack | Ashby |
|--------|-------|-------|
| Candidate | Name + cross-source badge if also in Ashby | Name + ASHBY badge + cross-source badge if also in Slack |
| Channel / Company | Formatted channel name (e.g., "Matter Intelligence") | Client org name (e.g., "Hedra") |
| Status | Inferred from emoji + thread keywords | Mapped from Ashby pipeline stage |
| AI Summary | LLM-generated summary of Slack thread | — |
| Days | Days since submission | Days in current stage |
| LinkedIn | Link to LinkedIn profile | Link if available |
| Stage / Thread | "View Thread" → opens side panel | Pipeline stage (clickable → opens in Ashby) |

### Thread panel (Slack only)
Click "View Thread" to open a side panel with the full Slack conversation. Reply directly from the panel with `@mention` autocomplete.

### AI enrichment (Slack only)
Click "Enrich with AI" to generate Claude-powered bullet-point summaries for all active Slack candidates. Summaries are persisted in the JSON file.

**Model config:**
```env
ENRICHMENT_MODEL=claude-sonnet-4-20250514
ENRICHMENT_MAX_TOKENS=500
```

---

## Status logic

### Slack candidates

| Status | Meaning |
|--------|---------|
| **CLOSED** | ⛔ reaction on the parent submission message, or explicit rejection keyword in thread |
| **IN PROCESS — explicit** | 👀 or ⏳ reaction, or explicit progress keyword in thread |
| **IN PROCESS — unclear** | No ⛔ and no explicit progress signal |

**DK's only required action:** Add ⛔ to a parent message when a candidate is declined.

### Ashby candidates

| Status | Mapping |
|--------|---------|
| **CLOSED** | Stage contains: reject, declined, archived, withdraw, no hire |
| **IN PROCESS — explicit** | A `pipelineStage` value is set |
| **IN PROCESS — unclear** | Only a `currentStage` value, no `pipelineStage` |

---

## Architecture

```
weekly_slack_recon/
├── serve_dashboard.py          # HTTP server + all API endpoints
├── dashboard.html              # Single-page dashboard UI
├── .env                        # Local config (not committed)
├── weekly_slack_reconciliation.json  # Persistent data store (Slack + Ashby)
│
└── src/weekly_slack_recon/
    ├── config.py               # Env-based configuration dataclass
    ├── slack_client.py         # Slack API wrapper
    ├── logic.py                # LinkedIn extraction, status inference
    ├── status_rules.py         # Emoji/keyword classification rules
    ├── reporting.py            # JSON/Markdown output writers
    ├── ashby_importer.py       # Ashby JSON → unified schema, DK filter
    ├── context_gatherer.py     # Gathers Slack thread context for LLM
    ├── enrichment.py           # Claude-powered candidate summaries
    ├── nudge.py                # Auto-nudge for stale submissions
    └── cli.py                  # CLI entry point
```

### API endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/status` | Generation job status |
| GET | `/api/generate` | Trigger Slack sync |
| GET | `/api/enrich/status` | Enrichment job status |
| POST | `/api/enrich` | Start AI enrichment |
| GET | `/api/thread` | Fetch Slack thread messages |
| GET | `/api/channel-members` | Get channel members for @mention |
| POST | `/api/send-followup` | Post message to a Slack channel |
| POST | `/api/send-thread-reply` | Reply to a Slack thread |
| GET | `/api/ashby/status` | Check Ashby export file status |
| POST | `/api/ashby/import` | Import & merge Ashby candidates |

---

## Running the server manually

```bash
cd /Users/david/Desktop/weekly_slack_recon
source .venv/bin/activate
python serve_dashboard.py
# Opens http://localhost:8001/dashboard.html automatically
```

Or double-click `Slack Reconciliation.app` on the Desktop.
