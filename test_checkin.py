#!/usr/bin/env python3
"""Quick test: run the Pipeline Status Check for Charta and Decagon only."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from dotenv import load_dotenv
load_dotenv()

from weekly_slack_recon.config import load_config
from weekly_slack_recon.slack_client import SlackAPI
from weekly_slack_recon.status_check_runner import run_status_check

cfg = load_config()
slack = SlackAPI(token=cfg.slack_bot_token)

def progress(phase, current, total, detail):
    print(f"  [{phase}] {current}/{total} — {detail}")

print("Running status check for Charta + Decagon...\n")
drafts = run_status_check(cfg, slack, progress_callback=progress, client_filter=["charta", "decagon"])

print(f"\n{'='*60}")
print(f"Generated {len(drafts)} draft(s)\n")

for draft in drafts:
    print(f"CLIENT: {draft.client_name}  (#{draft.channel_name})")
    print(f"CANDIDATES:")
    for c in draft.candidates:
        flag = " [FLAGGED]" if c.get("flag_for_review") else ""
        print(f"  • {c['name']} [{c['source']}] — {c['one_liner']}{flag}")
    print(f"\nMESSAGE:\n{draft.message_text}")
    print(f"{'='*60}\n")
