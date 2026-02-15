"""Slack Nudge runner - periodic check for stale submissions.

This module provides a simple polling-based approach that can be run:
1. Manually via CLI
2. On a schedule via cron (Linux/macOS) or Task Scheduler (Windows)
3. Via launchd on macOS for persistent background scheduling
"""

from __future__ import annotations

from datetime import datetime, timezone

from .config import Config, load_config
from .nudge import run_nudge_check


def run_single_check(dry_run: bool = False, dm_only: bool = None) -> None:
    """Run a single nudge check."""
    cfg = load_config()
    
    print(f"[{datetime.now(tz=timezone.utc).isoformat()}] Running nudge check...")
    print(f"Nudge threshold: {cfg.nudge_days} days without checkmark or no-entry emoji")
    effective_dm_only = dm_only if dm_only is not None else cfg.nudge_dm_only
    if effective_dm_only:
        print("Mode: DM-only (no thread replies)")
    print()
    
    results = run_nudge_check(cfg, dry_run=dry_run, dm_only=dm_only)
    
    print()
    print("=" * 50)
    print("NUDGE CHECK RESULTS")
    print("=" * 50)
    print(f"Submissions checked: {results['submissions_checked']}")
    print(f"Nudges needed: {results['nudges_needed']}")
    if dry_run:
        print(f"Nudges sent: (dry run - none sent)")
    else:
        print(f"Nudges sent: {results['nudges_sent']}")
    
    if results['submissions_needing_nudge']:
        print("\nSubmissions needing nudge:")
        for sub in results['submissions_needing_nudge']:
            print(f"  - {sub['candidate_name']} in #{sub['channel_name']} ({sub['days_since_submission']} days)")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Slack Nudge Checker")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Don't actually send nudges, just show what would be sent",
    )
    parser.add_argument(
        "--dm-only",
        action="store_true",
        default=None,
        help="Send DM summary only, don't post thread replies in channels",
    )
    
    args = parser.parse_args()
    run_single_check(dry_run=args.dry_run, dm_only=args.dm_only or None)
