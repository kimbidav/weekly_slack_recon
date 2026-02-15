from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

from rich.console import Console

from .config import load_config
from .slack_client import SlackAPI
from .logic import build_candidate_submissions
from .reporting import print_report, write_markdown, write_json, generate_followup_snippets


def main() -> None:
    console = Console()
    cfg = load_config()

    console.print("[bold]Weekly Slack Pipeline Reconciliation Tool[/bold]")

    slack = SlackAPI(token=cfg.slack_bot_token)

    console.print("Resolving DK Slack user by email...")
    dk_user_id = slack.get_user_id_by_email(cfg.dk_email)

    console.print("Discovering relevant channels (prefix 'candidatelabs-' and DK is member)...")
    channels = slack.list_candidate_channels_for_user(dk_user_id)

    if not channels:
        console.print("[yellow]No matching channels found.[/yellow]")
        return

    console.print(f"[green]Found {len(channels)} matching channel(s):[/green]")
    for ch in channels[:10]:  # Show first 10
        console.print(f"  - {ch.get('name', ch.get('id', 'unknown'))}")
    if len(channels) > 10:
        console.print(f"  ... and {len(channels) - 10} more")

    now = datetime.now(tz=timezone.utc)
    oldest_date = now - cfg.lookback_timedelta

    console.print(f"\nScanning messages from the last {cfg.lookback_days} days...")
    console.print(f"Date range: [dim]{oldest_date.strftime('%Y-%m-%d')} to {now.strftime('%Y-%m-%d')}[/dim]")
    console.print(f"DK User ID: [dim]{dk_user_id}[/dim]")
    submissions, stats = build_candidate_submissions(cfg, slack, dk_user_id, channels, now=now)
    
    console.print(f"[green]Found {len(submissions)} candidate submission(s)[/green]")
    console.print(f"[dim]Stats: {stats['total_messages']} total messages, {stats['top_level_messages']} top-level, {stats['dk_messages']} from DK, {stats['messages_with_linkedin']} with LinkedIn URLs[/dim]\n")

    print_report(submissions)

    if cfg.output_markdown_path:
        write_markdown(submissions, cfg.output_markdown_path, generated_at=now)
        console.print(f"\nMarkdown report written to [green]{cfg.output_markdown_path}[/green]")
        
        # Also write JSON for dashboard
        json_path = cfg.output_markdown_path.replace('.md', '.json')
        write_json(submissions, json_path, generated_at=now)
        console.print(f"JSON data written to [green]{json_path}[/green] (for dashboard)")

    # Optional: show follow-up snippets in the console
    snippets = generate_followup_snippets(submissions)
    if snippets:
        console.print("\n[bold underline]Suggested follow-up messages[/bold underline]")
        for channel_name, text in snippets.items():
            console.print(f"\n[bold cyan][{channel_name}][/bold cyan]")
            console.print(text)


def nudge_check() -> None:
    """Run a nudge check (CLI entry point).
    
    Finds submissions without a checkmark or no-entry emoji for N days
    and posts a follow-up message tagging David Kimball.
    """
    parser = argparse.ArgumentParser(description="Check for submissions needing nudges")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Don't send nudges, just show what would be sent",
    )
    parser.add_argument(
        "--dm-only",
        action="store_true",
        default=None,
        help="Send DM summary only, don't post thread replies in channels",
    )
    args = parser.parse_args()
    
    from .realtime_monitor import run_single_check
    run_single_check(dry_run=args.dry_run, dm_only=args.dm_only or None)


if __name__ == "__main__":
    main()
