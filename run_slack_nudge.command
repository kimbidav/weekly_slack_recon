#!/bin/bash
# Launcher script for Slack Nudge Check
# Double-click this file to run the nudge check

cd "$(dirname "$0")"

echo "=================================="
echo "  Slack Nudge Check"
echo "=================================="
echo ""

# Check if virtual environment exists
if [ ! -d ".venv" ]; then
    echo "Virtual environment not found. Please run: python3 -m venv .venv"
    echo "Then install dependencies: source .venv/bin/activate && pip install -r requirements.txt"
    read -p "Press Enter to exit..."
    exit 1
fi

# Activate virtual environment
source .venv/bin/activate

# Run the nudge check
PYTHONPATH=src python3 -m src.weekly_slack_recon.realtime_monitor

echo ""
echo "=================================="
echo "  Done! Check your Slack DMs for the summary."
echo "=================================="
read -p "Press Enter to close..."
