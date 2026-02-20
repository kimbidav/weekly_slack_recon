## Pipeline Reconciliation Dashboard (DK View)

A single-pane-of-glass tool for tracking all active candidates — across both **Slack submissions** and **Ashby ATS** — in one interactive dashboard. Built for David Kimball at Candidate Labs.

---

## What it does

| Source | What it tracks |
|--------|---------------|
| **Slack** | DK's top-level messages in `candidatelabs-*` channels that contain a LinkedIn URL. Status inferred from emoji reactions and thread keywords. |
| **Ashby** | Candidates credited to DK in the Ashby ATS. Extracted via the Ashby Automation tool (`~/Desktop/Ashby automation/`) and merged into the dashboard automatically. |

The dashboard merges both sources and flags candidates that appear in both (LinkedIn URL cross-match).

---

## Daily workflow

1. **Open the dashboard** — double-click `Slack Reconciliation.app` on the Desktop. The last synced data loads immediately. The header shows how fresh each source is: `Slack synced 2h ago · Ashby imported 45m ago`.
2. **When you want fresh data** — click **Sync Slack**. This scans all `candidatelabs-*` channels (~1–2 min due to rate limits) and automatically runs a fresh Ashby extraction at the end.
3. **If Ashby session expired** — a yellow banner appears after the sync. Paste a fresh `sessionToken` cookie from DevTools and click **Save & Sync**. The server saves it, re-extracts, and re-imports automatically.
4. **Review** — filter by status, channel/company, or source. Click stage links for Ashby candidates to jump straight to their Ashby page.

> **Tip:** You don't need to sync Slack every time you open the dashboard. The header freshness timestamps tell you whether the data is recent enough.

---

## Setup

### 1. Prerequisites

```bash
cd /Users/david/Desktop/weekly_slack_recon
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Also requires **Node.js** and the Ashby Automation tool at `~/Desktop/Ashby automation/` (separate project — see its own README for setup).

### 2. `.env` file

Create `.env` in the project root:

```env
# Slack token (User OAuth Token — no need to add a bot to channels)
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

Ashby data is extracted via the **Ashby Automation** tool at `~/Desktop/Ashby automation/` — a separate Node.js project that hits Ashby's internal GraphQL API using a saved session cookie.

**How it works end-to-end:**
1. Clicking **Sync Slack** automatically runs `node src/cli.ts extract` after the Slack scan completes, writing a fresh JSON to the output folder.
2. The server imports that JSON and merges it into the main data file.
3. If extraction fails (session expired), the dashboard shows a yellow re-auth banner.
4. Paste a fresh `sessionToken` cookie → server runs `node src/cli.ts auth-cookie --cookie <value>`, re-extracts, re-imports.

**What gets imported:**
- Only candidates where `creditedTo` is DK (`David`, `David Kimball`, `David CL`, `DK`)
- `company_name` shows the client org (`orgName` from Ashby — e.g., "Agave", "Canals")
- The Stage / Thread column links to `app.ashbyhq.com/candidates/{id}`

**Getting a fresh Ashby session cookie (when the banner appears):**
1. Open `app.ashbyhq.com` in Chrome and sign in
2. Open DevTools → Application → Cookies → `app.ashbyhq.com`
3. Copy the value of the `sessionToken` cookie
4. Paste it into the banner and click **Save & Sync**

**Manual Ashby import (fallback):**
The "Import Ashby" button in the header reads whatever `.json` is already in the output folder — it does not fetch new data. Use it only if you want to re-import without triggering a full Slack sync. The import progress line shows the file age so you know if it's stale.

---

## Dashboard features

### Data freshness
The header subtitle always shows: `Slack synced Xh ago · Ashby imported Yh ago`. Hover any age label for the exact timestamp.

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
| GET | `/api/status` | Slack sync job status (includes `ashby_auth_required` flag) |
| GET | `/api/generate` | Trigger Slack sync + Ashby extraction |
| GET | `/api/enrich/status` | AI enrichment job status |
| POST | `/api/enrich` | Start AI enrichment |
| POST | `/api/enrich/clear` | Clear all AI summaries |
| GET | `/api/thread` | Fetch Slack thread messages |
| GET | `/api/channel-members` | Get channel members for @mention autocomplete |
| POST | `/api/send-followup` | Post message to a Slack channel |
| POST | `/api/send-thread-reply` | Reply to a Slack thread |
| GET | `/api/ashby/status` | Ashby export file info (path, modified time, size) |
| POST | `/api/ashby/import` | Import latest Ashby JSON into the data file |
| POST | `/api/ashby/set-cookie` | Save Ashby session cookie, re-extract, re-import |

---

## Running the server manually

```bash
cd /Users/david/Desktop/weekly_slack_recon
source .venv/bin/activate
python serve_dashboard.py
# Opens http://localhost:8001/dashboard.html automatically
```

Or double-click `Slack Reconciliation.app` on the Desktop.
