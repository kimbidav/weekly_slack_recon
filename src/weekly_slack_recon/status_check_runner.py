"""
Orchestrator for the Pipeline Status Check workflow.

Steps:
  1. Load active candidates from Ashby JSON export
  2. Scan Slack for DK submission messages
  3. Merge and deduplicate by LinkedIn URL
  4. Group by client channel (skip CLOSED candidates)
  5. For each candidate, gather context from Slack thread, Gmail, and Calendar
  6. Synthesize per-candidate status using priority hierarchy
  7. Compose a draft check-in message per client using Claude
  8. Return a list of DraftMessage objects ready for dashboard review
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Callable, Optional

from .config import Config
from .slack_client import SlackAPI
from .logic import build_candidate_submissions, CandidateSubmission
from .context_gatherer import gather_context_for_submission
from .ashby_importer import load_ashby_export, merge_ashby_into_submissions, find_latest_ashby_export
from .status_synthesizer import synthesize_candidate_status, StatusSynthesis
from .message_composer import compose_checkin_message, DraftMessage


def _channel_to_client_name(channel_name: str) -> str:
    """
    Derive a display-friendly client name from a Slack channel name.
    e.g. 'candidatelabs-agave' → 'Agave'
         'candidatelabs-charta-health-fwd' → 'Charta Health'
    """
    name = channel_name.lower()
    # Strip known prefixes
    for prefix in ("candidatelabs-", "candidatelabs"):
        if name.startswith(prefix):
            name = name[len(prefix):]
    # Strip known suffixes
    for suffix in ("-fwd", "-forward", "-submissions"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    # Replace hyphens with spaces and title-case
    return name.replace("-", " ").strip().title()


def _candidate_first_name(full_name: str) -> str:
    """Return just the first name of a candidate."""
    return full_name.strip().split()[0] if full_name.strip() else full_name


def run_status_check(
    cfg: Config,
    slack: SlackAPI,
    progress_callback: Optional[Callable[[str, int, int, str], None]] = None,
    client_filter: Optional[list[str]] = None,
) -> list[DraftMessage]:
    """
    Run the full Pipeline Status Check pipeline.

    Args:
        cfg:               Loaded Config object.
        slack:             Authenticated SlackAPI instance.
        progress_callback: Optional fn(phase, current, total, detail) for UI progress.
        client_filter:     Optional list of client name substrings to limit processing
                           (e.g. ["charta", "decagon"]). Case-insensitive.

    Returns:
        List of DraftMessage objects, one per active client.
    """

    def progress(phase: str, current: int, total: int, detail: str):
        if progress_callback:
            progress_callback(phase, current, total, detail)
        print(f"[STATUS-CHECK] {phase} ({current}/{total}): {detail}")

    progress("starting", 0, 1, "Initializing...")

    # ── 1. Resolve DK user ID ────────────────────────────────────────────────
    dk_user_id = cfg.dk_user_id or slack.get_user_id_by_email(cfg.dk_email)
    progress("starting", 0, 1, f"DK user ID: {dk_user_id}")

    # ── 2. Discover channels ─────────────────────────────────────────────────
    progress("scanning", 0, 1, "Discovering candidate channels...")
    channels = slack.list_candidate_channels_for_user(dk_user_id)
    if not channels:
        progress("error", 0, 0, "No candidate channels found")
        return []

    progress("scanning", 0, 1, f"Found {len(channels)} channels. Scanning Slack submissions...")

    # ── 3. Build Slack submission list ───────────────────────────────────────
    now = datetime.now(tz=timezone.utc)
    submissions, _stats = build_candidate_submissions(cfg, slack, dk_user_id, channels, now=now)

    # ── 4. Load and merge Ashby data ─────────────────────────────────────────
    ashby_records_by_linkedin: dict[str, dict] = {}
    if cfg.ashby_json_path:
        try:
            ashby_file = find_latest_ashby_export(cfg.ashby_json_path)
            ashby_raw = load_ashby_export(ashby_file)
            # Build lookup by LinkedIn URL for fast retrieval
            for rec in ashby_raw:
                li = (rec.get("linkedin_url") or "").strip().lower()
                if li:
                    ashby_records_by_linkedin[li] = rec
            progress("scanning", 0, 1, f"Loaded {len(ashby_raw)} Ashby candidates")
        except Exception as e:
            print(f"[STATUS-CHECK] Ashby load failed (continuing without): {e}")

    # ── 5. Filter to active (non-CLOSED) submissions only ────────────────────
    active_submissions = [s for s in submissions if s.status != "CLOSED"]

    # Optional client filter (e.g. for testing)
    if client_filter:
        filter_lower = [f.lower() for f in client_filter]
        active_submissions = [
            s for s in active_submissions
            if any(f in s.channel_name.lower() for f in filter_lower)
        ]
    progress("gathering", 0, len(active_submissions), f"Processing {len(active_submissions)} active candidates...")

    # ── 6. Initialize Google clients (graceful degradation if unavailable) ───
    gmail_client = None
    calendar_client = None

    try:
        from .gmail_client import GmailClient
        gmail_client = GmailClient(
            credentials_path=cfg.gmail_credentials_path,
            token_path=cfg.gmail_token_path,
        )
        progress("gathering", 0, 1, "Gmail client initialized")
    except FileNotFoundError:
        progress("gathering", 0, 1, "Gmail not configured — skipping email context")
    except Exception as e:
        print(f"[STATUS-CHECK] Gmail init failed: {e}")

    try:
        from .calendar_client import CalendarClient
        calendar_client = CalendarClient(
            credentials_path=cfg.gmail_credentials_path,  # Same credentials file
            token_path=cfg.gcal_token_path,
        )
        progress("gathering", 0, 1, "Calendar client initialized")
    except FileNotFoundError:
        progress("gathering", 0, 1, "Calendar not configured — skipping calendar context")
    except Exception as e:
        print(f"[STATUS-CHECK] Calendar init failed: {e}")

    # ── 7. Gather context and synthesize status per candidate ────────────────
    user_cache: dict[str, str] = {}
    # Group by channel for composing messages
    by_channel: dict[str, list[StatusSynthesis]] = {}
    channel_meta: dict[str, dict] = {}  # channel_name → {channel_id, client_name}

    for idx, submission in enumerate(active_submissions):
        progress("gathering", idx + 1, len(active_submissions), submission.candidate_name)

        # Slack thread context
        try:
            ctx = gather_context_for_submission(cfg, slack, submission, user_cache)
            thread_messages = [
                {
                    "author": m.author,
                    "text": m.text,
                    "timestamp": m.timestamp.isoformat(),
                    "is_parent": not m.is_thread_reply,
                }
                for m in ctx.thread_messages
            ]
        except Exception as e:
            print(f"[STATUS-CHECK] Slack context error for {submission.candidate_name}: {e}")
            thread_messages = []

        # Gmail context
        email_signals = []
        if gmail_client:
            try:
                client_name = _channel_to_client_name(submission.channel_name)
                email_signals = gmail_client.search_emails(
                    candidate_name=submission.candidate_name,
                    client_name=client_name,
                    lookback_days=60,
                )
            except Exception as e:
                print(f"[STATUS-CHECK] Gmail error for {submission.candidate_name}: {e}")

        # Calendar context
        calendar_events = []
        if calendar_client:
            try:
                first_name = _candidate_first_name(submission.candidate_name)
                client_name = _channel_to_client_name(submission.channel_name)
                calendar_events = calendar_client.search_events(
                    candidate_first_name=first_name,
                    client_name=client_name,
                    lookback_days=cfg.gcal_lookback_days,
                    lookahead_days=cfg.gcal_lookahead_days,
                )
            except Exception as e:
                print(f"[STATUS-CHECK] Calendar error for {submission.candidate_name}: {e}")

        # Ashby record for this candidate
        li_key = (submission.linkedin_url or "").strip().lower()
        ashby_record = ashby_records_by_linkedin.get(li_key)

        # Synthesize status
        synthesis = synthesize_candidate_status(
            candidate_name=submission.candidate_name,
            ashby_record=ashby_record,
            slack_thread_messages=thread_messages,
            email_signals=email_signals,
            calendar_events=calendar_events,
        )

        # Group by channel
        ch = submission.channel_name
        if ch not in by_channel:
            by_channel[ch] = []
            channel_meta[ch] = {
                "channel_id": submission.channel_id,
                "client_name": _channel_to_client_name(ch),
            }
        by_channel[ch].append(synthesis)

    # ── 8. Compose a draft message per client ────────────────────────────────
    total_clients = len(by_channel)
    drafts: list[DraftMessage] = []

    for client_idx, (channel_name, syntheses) in enumerate(by_channel.items()):
        meta = channel_meta[channel_name]
        client_name = meta["client_name"]
        channel_id = meta["channel_id"]

        progress("composing", client_idx + 1, total_clients, f"Drafting message for {client_name}...")

        # Skip clients where all candidates are flagged for review
        visible = [s for s in syntheses if not s.flag_for_review]
        if not visible:
            print(f"[STATUS-CHECK] All candidates flagged for review in {client_name} — skipping draft")
            continue

        try:
            message_text = compose_checkin_message(
                client_name=client_name,
                candidate_syntheses=syntheses,
                model=cfg.status_check_model,
                anthropic_api_key=cfg.anthropic_api_key,
            )
        except Exception as e:
            print(f"[STATUS-CHECK] Compose error for {client_name}: {e}")
            message_text = _fallback_message(syntheses)

        if not message_text:
            continue

        # Build candidate list for UI display
        candidates_display = [
            {
                "name": s.candidate_name,
                "one_liner": s.one_liner,
                "confidence": s.confidence,
                "source": s.status_source,
                "flag_for_review": s.flag_for_review,
                "supporting_context": s.supporting_context,
            }
            for s in syntheses
        ]

        drafts.append(DraftMessage(
            draft_id=str(uuid.uuid4()),
            client_name=client_name,
            channel_id=channel_id,
            channel_name=channel_name,
            message_text=message_text,
            candidates=candidates_display,
            status="pending",
        ))

    progress("complete", total_clients, total_clients, f"Done! {len(drafts)} drafts ready.")
    return drafts


def _fallback_message(syntheses: list[StatusSynthesis]) -> str:
    """Generate a simple fallback message if Claude is unavailable."""
    lines = ["Hey team! Quick check-in on my candidates:"]
    for s in syntheses:
        if not s.flag_for_review:
            lines.append(f"– {s.candidate_name} — {s.one_liner}")
    lines.append("\nLet me know if you need anything else!")
    lines.append("-- by Claude <3")
    return "\n".join(lines)
