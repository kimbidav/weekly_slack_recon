# Quick Start Guide

## First Time Setup

1. **Set up virtual environment** (if not already done):
   ```bash
   cd /Users/david/Desktop/weekly_slack_recon
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Configure Slack Token**:
   Create a `.env` file in the project root:
   ```env
   SLACK_BOT_TOKEN=xoxp-your-token-here
   DK_EMAIL=dkimball@candidatelabs.com
   ```

## Running the GUI

### Method 1: Double-click launcher (Easiest)
- Simply double-click `run_gui.command`
- The GUI will open where you can configure settings and run

### Method 2: Create a Desktop App
1. Run: `./create_app.sh`
2. This creates `Slack Reconciliation.app`
3. Drag it to your Desktop or Applications folder
4. Double-click to launch anytime

### Method 3: Run directly
```bash
source .venv/bin/activate
PYTHONPATH=src python gui_app.py
```

## Using the GUI

1. **Configure Settings**:
   - **Lookback Days**: How many days back to scan (default: 30)
   - **Unclear Followup Days**: Minimum days before flagging for follow-up (default: 7)
   - **Inactivity Days**: Days without activity threshold (default: 5)
   - **Include Confused Close**: Check to treat :confused: as close signal

2. **Enter Slack Token** (optional):
   - If you leave this empty, it will use the token from `.env` file
   - You can override the .env token by entering one here

3. **Click "Run Reconciliation"**:
   - The tool will scan Slack channels
   - Progress and results appear in the output area
   - When complete, you'll see a summary

4. **View Results**:
   - Click "Open Output File" to view the generated Markdown report
   - The report is saved as `weekly_slack_reconciliation.md`

## Troubleshooting

- **"Virtual environment not found"**: Run the setup steps above
- **"Missing Token"**: Make sure you have a `.env` file with `SLACK_BOT_TOKEN` set
- **GUI won't open**: Make sure tkinter is installed (usually comes with Python on macOS)

