## Weekly Slack Pipeline Reconciliation Tool (DK View)

This is a weekly, read-only reconciliation tool that produces a clear, actionable snapshot of all candidates submitted by DK (`dkimball@candidatelabs.com`) across relevant external Slack channels, grouped by status.

### High-Level

- **Batch job**: Run manually (e.g., once per week) from your laptop.
- **Read-only**: Uses a Slack bot token with read-only scopes.
- **Scope**:
  - Only channels whose name starts with `candidatelabs-`.
  - Only channels where DK is a member.
  - Only top-level messages posted by DK that contain a LinkedIn URL, within a recent lookback window.

### Setup

You have two options for authentication:

#### Option 1: User OAuth Token (Recommended for single-user tool)

Since DK is already a member of the channels, using a **User OAuth Token** is simpler—no need to add a bot to channels.

1. **Create a Slack app**:
   - Go to `https://api.slack.com/apps` and create a new app for your workspace.
   - Under **OAuth & Permissions**, add these **User Token Scopes**:
     - `channels:read`
     - `groups:read`
     - `channels:history`
     - `groups:history`
     - `users:read.email` (to look up DK by email)
     - `reactions:read`
   - Under **User Token Scopes**, click **Add New Scopes** and add the above.
   - Scroll up and click **Install to Workspace**.
   - Authorize the app for your account (DK's account).
   - Copy the **User OAuth Token** (starts with `xoxp-...`) from the **OAuth & Permissions** page.

**Note:** Timestamps and message metadata are included automatically with message history—no additional scopes needed.

#### Option 2: Bot Token (Alternative)

If you prefer using a bot token instead:

1. **Create a Slack app**:
   - Go to `https://api.slack.com/apps` and create a new app for your workspace.
   - Under **OAuth & Permissions**, add these **Bot Token Scopes**:
     - `channels:read`
     - `groups:read`
     - `channels:history`
     - `groups:history`
     - `users:read`
     - `reactions:read`
   - Install the app to your workspace and copy the **Bot User OAuth Token** (starts with `xoxb-...`).
   - **Important:** You'll need to add the bot to each `candidatelabs-*` channel you want to scan.

2. **Configure environment variables**

   Create a `.env` file in the project root (`/Users/david/Desktop/weekly_slack_recon/.env`):

   ```env
   SLACK_BOT_TOKEN=xoxp-...  # or xoxb-... if using bot token
   DK_EMAIL=dkimball@candidatelabs.com
   LOOKBACK_DAYS=30
   UNCLEAR_FOLLOWUP_DAYS=7
   INACTIVITY_DAYS=5
   INCLUDE_CONFUSED_CLOSE=false
   ```

   - **`LOOKBACK_DAYS`**: How far back to scan for submissions (30–45 days typical).
   - **`UNCLEAR_FOLLOWUP_DAYS`**: Min days since submission for "in process — unclear" to be flagged as needs follow-up.
   - **`INACTIVITY_DAYS`**: No activity in this many days → candidate is actionable.

### Running the tool

#### Option 1: GUI (Recommended)

The easiest way to run the tool is using the graphical interface:

**Simple Method (Double-click):**
1. Double-click `run_gui.command` to launch the GUI
2. Configure your settings (lookback period, etc.) in the GUI
3. Click "Run Reconciliation"
4. View results and click "Open Output File" to see the report

**Create Desktop Icon (macOS App):**
1. Run the setup script: `./create_app.sh`
2. This creates a `Slack Reconciliation.app` bundle
3. Drag the app to your Applications folder or Desktop
4. Double-click to launch anytime

The GUI allows you to:
- Configure lookback period, follow-up days, and inactivity threshold
- Run reconciliation with custom settings
- View output and results in real-time
- Open the generated Markdown report file

#### Option 2: Interactive Dashboard (Web)

After running the reconciliation tool (which now generates both `.md` and `.json` files), you can view an interactive dashboard:

**To open the dashboard:**
1. Run the reconciliation tool first (GUI or CLI) to generate `weekly_slack_reconciliation.json`
2. Double-click `open_dashboard.sh` or open `dashboard.html` in your browser
3. The dashboard will load automatically from the JSON file

**Dashboard features:**
- **Filterable**: Filter by status (CLOSED, IN PROCESS — explicit, IN PROCESS — unclear) or channel
- **Sortable**: Click column headers to sort by candidate name, channel, status, or days since submission
- **Searchable**: Search candidates by name
- **Summary stats**: View totals for each status category and follow-ups
- **Clean interface**: Modern, responsive design with color-coded status badges

#### Option 3: CLI

Run from command line:

```bash
cd /Users/david/Desktop/weekly_slack_recon
source .venv/bin/activate
PYTHONPATH=src python -m weekly_slack_recon.cli
```

This will:

- Discover channels starting with `candidatelabs-` where DK is a member
- Find DK's top-level messages containing LinkedIn URLs within the lookback window
- Infer status per candidate (`CLOSED`, `IN PROCESS — explicit`, `IN PROCESS — unclear`)
- Flag "in process — unclear" candidates that need follow-up
- Print a grouped, human-readable report to the terminal
- Write a Markdown file (`weekly_slack_reconciliation.md`) with the full report
- Show suggested follow-up messages for channels with unclear candidates

### Adjusting Parameters

**Using the GUI:**
- All parameters can be configured directly in the GUI interface before running

**Using .env file (for CLI or GUI defaults):**
Edit the `.env` file to change:
- `LOOKBACK_DAYS` - How far back to scan (default: 30)
- `UNCLEAR_FOLLOWUP_DAYS` - Min days for follow-up flagging (default: 7)  
- `INACTIVITY_DAYS` - Inactivity threshold (default: 5)
- `INCLUDE_CONFUSED_CLOSE` - Treat :confused: as close signal (default: false)

### Authoritative Manual Signals (DK Annotations)

- DK may manually annotate candidate status in real time by adding emoji reactions to the **parent submission message** in Slack.
- These annotations are treated as authoritative state overrides and take precedence over inferred signals from thread replies or keywords.

**Canonical emojis**

- **⛔**: Declined / Closed – terminal state. Overrides all other signals.
- **👀**: Actively in process – explicit in-process signal.
- **⏳**: Waiting / pending – treated as in-process.

Only emoji reactions on the **parent submission message** are treated as authoritative manual annotations.

### Status Definitions

- **CLOSED**: Explicit disqualification based on close signals (including ⛔ on the parent message).
- **IN PROCESS — explicit**: In-process with explicit signals (emoji or keywords) indicating movement.
- **IN PROCESS — unclear**: A candidate with no explicit close signal (⛔) and no explicit progress signal. Absence of a decline implies the candidate is still in process.

### User Responsibilities (Minimal)

DK's only required manual action:

- Add **⛔** to the parent submission message when a candidate is definitively declined.

Optional:

- Add **👀** to indicate explicit progress.

DK is **not** required to:

- Update threads.
- Add notes.
- Annotate intermediate steps.
- Maintain external systems.

### Acceptance Tests

- If a submission message contains ⛔, the candidate is marked CLOSED even if:
  - Thread replies suggest progress.
  - Other reactions indicate movement.
  - Keywords imply ambiguity.
- If a submission has no ⛔, it must appear as IN PROCESS.
- Submissions without ⛔ and without explicit progress signals must appear under: **IN PROCESS — unclear**.
- Weekly output must contain all DK submissions in relevant channels within the lookback window.

### AI Enrichment (LLM-Powered Summaries)

The dashboard includes an **"Enrich with AI"** button that uses Claude to generate concise, bullet-point summaries for each candidate — so you don't have to read through individual Slack threads to know what's happening.

#### How it works

1. **Context gathering**: For each candidate, the tool collects:
   - The full submission thread (all replies from any user, including external contacts)
   - Channel-wide messages that mention the candidate by name (within the lookback window), plus threads on those messages
   - Name matching includes common nicknames (e.g., "Andrew" also searches for "Andy", "Drew")

2. **LLM analysis**: The gathered context is sent to Claude, which produces a chronological bullet-point summary of key developments (interviews, feedback, offers, rejections, next steps, etc.)

3. **Dashboard display**: Summaries appear in the "AI Summary" column and are persisted in the JSON data file.

#### Setup

Add your Anthropic API key to `.env`:

```env
ANTHROPIC_API_KEY=sk-ant-api03-...
```

Optional settings:

```env
ENRICHMENT_MODEL=claude-sonnet-4-20250514    # Claude model to use
ENRICHMENT_MAX_TOKENS=500                  # Max tokens per summary
```

#### Usage

1. Run **Generate Data** first to create the submissions dataset
2. Click **Enrich with AI** to run enrichment on all candidates
3. Progress is shown in the header (gathering context, then analyzing with Claude)
4. Summaries are saved to the JSON file and persist across page reloads

#### Future: Email & Calendar Integration

Planned additional context sources:
- **Gmail integration**: Capture email threads with candidates (matched via Gem.com API using LinkedIn-to-email mapping)
- **Calendar integration**: Detect interview events (e.g., "Andrew x Argus" on calendar)

### Architecture

```
src/weekly_slack_recon/
├── config.py              # Environment-based configuration
├── slack_client.py        # Slack API wrapper (read messages, post replies/DMs)
├── logic.py               # Core: LinkedIn extraction, status inference, submission building
├── status_rules.py        # Emoji/keyword classification rules
├── reporting.py           # Output: console (rich), Markdown, CSV, JSON
├── nudge.py               # Auto-nudge for stale submissions
├── realtime_monitor.py    # Scheduled nudge runner (cron/launchd)
├── context_gatherer.py    # Gathers Slack context for LLM enrichment
├── enrichment.py          # Claude-powered candidate summary generation
└── cli.py                 # CLI entry points
```

### Notes

- This is intentionally **read-only** and does **not** auto-post to Slack (except for the nudge and follow-up features which can be enabled separately).
- Logic for emojis/keywords and thresholds is implemented in a modular way in `status_rules.py` and `logic.py`, so it's easy to tweak.
- AI enrichment results are merged into the existing JSON data file, so re-running "Generate Data" will clear them (re-enrich after regenerating).
