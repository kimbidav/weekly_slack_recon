#!/bin/bash
cd "$(dirname "$0")"
source .venv/bin/activate
PYTHONPATH=src python -m weekly_slack_recon.cli
