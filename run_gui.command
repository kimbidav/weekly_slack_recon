#!/bin/bash
# Launcher script for Weekly Slack Reconciliation GUI

cd "$(dirname "$0")"

# Check if virtual environment exists
if [ ! -d ".venv" ]; then
    echo "Virtual environment not found. Please run: python3 -m venv .venv"
    echo "Then install dependencies: source .venv/bin/activate && pip install -r requirements.txt"
    exit 1
fi

# Activate virtual environment
source .venv/bin/activate

# Run the GUI application
PYTHONPATH=src python gui_app.py

