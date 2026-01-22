#!/bin/bash
# Open the dashboard with a local server (fixes CORS issues)

cd "$(dirname "$0")"

# Check if JSON file exists
if [ ! -f "weekly_slack_reconciliation.json" ]; then
    echo "JSON file not found. Please run the reconciliation tool first:"
    echo "  source .venv/bin/activate && PYTHONPATH=src python -m weekly_slack_recon.cli"
    echo ""
    echo "Or use the GUI or desktop app to generate the data."
    exit 1
fi

# Start the server
python3 serve_dashboard.py
