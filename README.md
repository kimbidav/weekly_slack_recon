## Pipeline Reconciliation Dashboard (DK View)

A single-pane-of-glass tool for tracking all active candidates — across **Slack submissions**, **Ashby ATS**, **Gmail**, and **Google Calendar** — in one interactive dashboard. Built for David Kimball at Candidate Labs.

---

## What it does

| Source | What it tracks |
|--------|---------------|
| **Slack** | DK's top-level messages in `candidatelabs-*` channels that contain a LinkedIn URL. Status inferred from emoji reactions and thread keywords. |
| **Ashby** | Candidates credited to DK in the Ashby ATS. Extracted via the Ashby Automation tool and merged automatically. Only DK-credited records (`David`, `David Kimball`, `David CL`, `DK`) are imported. |
| **Gmail** | Emails where DK is in To or CC, searched by candidate name. Used by the Check-Ins agent to detect advancement, scheduling, and rejection signals. |
| **Google Calendar** | DK's primary calendar, searched for events matching `"{candidate} x {client}"`. A scheduled interview is the highest-confidence status signal. |

---

## Daily workflow

1. **Open the dashboard** — double-click `Slack Reconciliation.app` on the Desktop. Last synced data loads immediately. Header shows: `Slack synced 2h ago · Ashby imported 45m ago`.
2. **Sync Slack** — click **Sync Slack** to scan all `candidatelabs-*` channels (~1–2 min) and auto-run Ashby extraction.
3. **Sync Ashby** — click **Sync Ashby** to run a fresh Ashby extraction and import. If the session is expired, the cookie prompt appears inline — no separate step needed.
4. **Generate Check-Ins** — click the **Check-Ins** tab, then **Generate Check-Ins** to automatically draft client-facing check-in messages for all active clients. Review and approve each one before it posts.

> **Tip:** You don't need to sync every time you open the dashboard. The freshness timestamps in the header tell you if the data is recent enough.

---

## Setup

### 1. Prerequisites

```bash
cd /Users/david/Desktop/weekly_slack_recon
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Also requires **Node.js** and the Ashby Automation tool at `~/Desktop/Ashby automation/` (separate project).

### 2. `.env` file

```env
# Slack token (User OAuth Token — xoxp-...)
SLACK_BOT_TOKEN=xoxp-...

# DK's email (used to look up Slack user ID)
DK_EMAIL=dkimball@candidatelabs.com

# How far back to scan Slack for submissions
LOOKBACK_DAYS=45

# Thresholds for flagging follow-ups
UNCLEAR_FOLLOWUP_DAYS=7
INACTIVITY_DAYS=5

# Anthropic API key for AI enrichment + Check-Ins
ANTHROPIC_API_KEY=sk-ant-api03-...

# Path to Ashby JSON export directory
ASHBY_JSON_PATH=/Users/david/Desktop/Ashby automation/output

# Pipeline Status Check (Check-Ins tab)
GMAIL_CREDENTIALS_PATH=./credentials.json   # Google OAuth credentials
GMAIL_TOKEN_PATH=./gmail_token.json          # Cached Gmail token (auto-created)
GCAL_TOKEN_PATH=./gcal_token.json            # Cached Calendar token (auto-created)
GCAL_LOOKBACK_DAYS=7                         # Days in the past to search calendar
GCAL_LOOKAHEAD_DAYS=14                       # Days in the future to search calendar
STATUS_CHECK_MODEL=claude-sonnet-4-6         # Claude model for drafting messages
CLIENT_CONTACT_MAP={}                        # Optional: {"Agave": "Akshay"} for named greetings
```

### 3. Slack app scopes

Create a Slack app at https://api.slack.com/apps with these **User Token Scopes**:
`channels:read`, `groups:read`, `channels:history`, `groups:history`, `users:read`, `users:read.email`, `reactions:read`, `chat:write`

### 4. Google OAuth setup (for Check-Ins tab)

Required once to enable Gmail and Calendar access for the Check-Ins agent.

1. Go to [console.cloud.google.com](https://console.cloud.google.com) → create a project
2. Enable **Gmail API** and **Google Calendar API**
3. OAuth consent screen → add scopes: `gmail.readonly`, `calendar.readonly`
4. Credentials → Create OAuth 2.0 Client ID → **Desktop app** → Download JSON
5. Save the downloaded file as `credentials.json` in the project root
6. First time you click **Generate Check-Ins**, a browser window will open for one-time authorization. Tokens are then cached to `gmail_token.json` and `gcal_token.json` automatically.

---

## Check-Ins tab (Pipeline Status Check)

The Check-Ins tab automates weekly client check-in messages. It replaces ~45 min of manual research per client with a 2-minute review-and-approve workflow.

### How it works

1. Click **Generate Check-Ins** in the Check-Ins tab
2. The agent identifies all active clients with DK-submitted candidates (from Slack + Ashby)
3. For each candidate, it gathers fresh context from four sources in priority order:

| Priority | Source | Signal |
|----------|--------|--------|
| 1 (highest) | **Google Calendar** | Scheduled interview → strongest signal of advancement |
| 2 | **Gmail** | Emails where DK is CC'd — advancement decisions, scheduling, rejections |
| 3 | **Slack thread** | Client's initial reaction and early-stage decisions |
| 4 (lowest) | **Ashby ATS** | Baseline pipeline stage (often lags behind real state) |

4. Synthesizes a per-candidate status one-liner reflecting the most current known state
5. Drafts a professional, client-facing message per client using Claude
6. Displays all drafts as editable cards for review
7. Click **Approve & Send** per client (or **Approve All**) to post directly to the Slack Connect channel

### Draft message format

```
Hey team! Quick check-in on my candidates:
– Candidate Name — status one-liner
– Candidate Name — status one-liner
Warm closing sentence.
-- by Claude <3
```

### One-liner rules

- **Calendar event exists** → lead with the event: `"onsite is set for 2/25 — excited to see how it goes!"`
- **Email shows advancement** → reference it: `"advanced to next stage as of 2/14 — any update?"`
- **Slack thread context only** → reference last decision point: `"coding challenge sent Feb 12 — any update from him?"`
- **No signal** → open question: `"any update on where things stand here?"`
- Never states uncertain information as fact — ambiguity becomes a question

### Soft pass handling

If Slack or email contains language like "comp mismatch", "keeping warm", or "table this", the candidate is flagged for DK review and excluded from the draft by default.

---

## Ashby integration

Ashby data is extracted via the **Ashby Automation** tool at `~/Desktop/Ashby automation/`.

**Sync Ashby button:**
1. Runs `node src/cli.ts extract` to generate a fresh JSON export
2. Imports DK-only candidates and merges into the dashboard
3. If session expired → cookie prompt appears inline in the dashboard
4. Paste a fresh `sessionToken` cookie → server re-auths, re-extracts, re-imports

**Getting a fresh Ashby session cookie:**
1. Open `app.ashbyhq.com` in Chrome → sign in
2. DevTools → Application → Cookies → `app.ashbyhq.com`
3. Copy value of the `sessionToken` cookie
4. Paste into the banner and click **Save & Sync**

**DK filter:** Only candidates where `creditedTo` is `David`, `David Kimball`, `David CL`, or `DK` are imported.

---

## Dashboard features

### Pipeline tab

- **Status filter**: CLOSED / IN PROCESS — explicit / IN PROCESS — unclear
- **Channel filter**: All `candidatelabs-*` channels shown as clean client names
- **Source filter**: All / Slack only / Ashby only
- **Search**: Candidate name, company, job title
- **Thread panel**: Click "View Thread" to open the full Slack conversation with inline reply and `@mention` autocomplete
- **AI enrichment**: "Enrich with AI" generates Claude-powered bullet-point summaries for active Slack candidates

### Check-Ins tab

- **Generate Check-Ins**: Runs the full 4-source pipeline and drafts messages for all active clients
- **Draft cards**: One card per client with editable message textarea and per-candidate one-liner breakdown
- **Source badges**: Each candidate shows which source drove the status (calendar / gmail / slack / ashby)
- **Approve & Send**: Posts the message to the client's Slack Connect channel via `xoxp` user token
- **Skip**: Exclude a client from the current batch without deleting the draft
- **Approve All**: Send all pending drafts at once

---

## Status logic

### Slack candidates

| Status | Meaning |
|--------|---------|
| **CLOSED** | ⛔ on parent message, or hard rejection keyword in thread |
| **IN PROCESS — explicit** | ✅ reaction, or interview/onsite/screen keyword in thread |
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
├── dashboard.html              # Single-page dashboard UI (Pipeline + Check-Ins tabs)
├── .env                        # Local config (not committed)
├── credentials.json            # Google OAuth credentials (not committed)
├── weekly_slack_reconciliation.json  # Persistent data store (Slack + Ashby)
├── status_check_log.json       # Audit log of sent check-in messages
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
    ├── cli.py                  # CLI entry point
    ├── google_auth_helper.py   # Shared Google OAuth2 flow
    ├── gmail_client.py         # Gmail API — search emails by candidate/client
    ├── calendar_client.py      # Google Calendar API — search interview events
    ├── status_synthesizer.py   # Multi-source status synthesis (priority hierarchy)
    ├── message_composer.py     # Claude-powered check-in message drafting
    └── status_check_runner.py  # Check-Ins orchestrator
```

### API endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/status` | Slack sync job status |
| GET/POST | `/api/generate` | Trigger Slack sync + Ashby extraction |
| GET | `/api/enrich/status` | AI enrichment job status |
| POST | `/api/enrich` | Start AI enrichment |
| POST | `/api/enrich/clear` | Clear all AI summaries |
| GET | `/api/thread` | Fetch Slack thread messages |
| GET | `/api/channel-members` | Channel members for @mention autocomplete |
| POST | `/api/send-followup` | Post message to a Slack channel |
| POST | `/api/send-thread-reply` | Reply to a Slack thread |
| GET | `/api/ashby/status` | Ashby export file info |
| POST | `/api/ashby/sync` | Run Ashby extraction + import (background) |
| GET | `/api/ashby/sync/status` | Poll Ashby sync progress |
| POST | `/api/ashby/import` | Import existing Ashby JSON (no extraction) |
| POST | `/api/ashby/set-cookie` | Save session cookie, re-extract, re-import |
| POST | `/api/status-check/generate` | Start Check-Ins pipeline (background) |
| GET | `/api/status-check/status` | Poll Check-Ins pipeline progress |
| GET | `/api/status-check/drafts` | Fetch all drafted messages |
| PUT | `/api/status-check/drafts/:id` | Edit draft message or mark skipped |
| POST | `/api/status-check/approve` | Approve and post one or all drafts |

---

## Running the server manually

```bash
cd /Users/david/Desktop/weekly_slack_recon
source .venv/bin/activate
python serve_dashboard.py
# Opens http://localhost:8001/dashboard.html automatically
```

Or double-click `Slack Reconciliation.app` on the Desktop.
