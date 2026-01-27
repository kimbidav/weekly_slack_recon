#!/bin/bash
# Run the Slack nudge check
# Can be scheduled via cron or launchd

cd "$(dirname "$0")"

# Activate virtual environment if it exists
if [ -d "venv" ]; then
    source venv/bin/activate
elif [ -d ".venv" ]; then
    source .venv/bin/activate
fi

# Run the nudge check
python3 -m src.weekly_slack_recon.realtime_monitor "$@"
