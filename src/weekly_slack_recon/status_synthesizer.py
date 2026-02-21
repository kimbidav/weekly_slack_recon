"""
Status synthesizer for the Pipeline Status Check workflow.
Merges context from four data sources — Google Calendar, Gmail, Slack thread,
and Ashby ATS — using a priority hierarchy to produce a per-candidate status
one-liner and confidence level.

Priority (highest → lowest):
  1. Google Calendar  — a scheduled event is the strongest signal of advancement
  2. Gmail            — emails from/to client hiring team reveal current state
  3. Slack thread     — captures initial decisions but often goes stale
  4. Ashby ATS        — baseline pipeline stage, frequently out of date
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from .gmail_client import EmailSignal, SIGNAL_ADVANCEMENT, SIGNAL_SCHEDULING, SIGNAL_REJECTION
from .calendar_client import CalendarEvent

# Confidence levels
CONFIDENCE_HIGH = "high"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_LOW = "low"

# Source labels
SOURCE_CALENDAR = "calendar"
SOURCE_GMAIL = "gmail"
SOURCE_SLACK = "slack"
SOURCE_ASHBY = "ashby"
SOURCE_NONE = "none"

# Soft-pass keywords — when these appear in Slack/email, flag for DK review
_SOFT_PASS_KEYWORDS = [
    "comp mismatch", "compensation mismatch", "salary mismatch",
    "over budget", "overqualified", "underqualified",
    "not the right time", "not a priority", "keeping warm",
    "table this", "hold off", "put a pin",
    "concerned about", "hesitant", "on the fence",
]


def _contains_soft_pass(texts: list[str]) -> bool:
    """Return True if any text contains soft-pass language."""
    combined = " ".join(texts).lower()
    return any(kw in combined for kw in _SOFT_PASS_KEYWORDS)


def _format_event_date(dt: datetime) -> str:
    """Format a datetime for use in a one-liner (e.g. '2/23')."""
    return f"{dt.month}/{dt.day}"


def _extract_stage_from_event(summary: str) -> str:
    """
    Guess the interview stage from an event title.
    e.g. 'Louise x Charta technical' → 'technical'
         'Maanav x Charta onsite' → 'onsite'
    """
    summary_lower = summary.lower()
    for stage in ["onsite", "technical", "tech screen", "coding", "loop", "final", "intro", "phone"]:
        if stage in summary_lower:
            return stage
    return "interview"


@dataclass
class StatusSynthesis:
    """Result of synthesizing a candidate's status from all available sources."""
    candidate_name: str
    status_source: str          # calendar / gmail / slack / ashby / none
    one_liner: str              # The client-facing status sentence
    confidence: str             # high / medium / low
    flag_for_review: bool = False  # True for soft passes — exclude from draft by default
    supporting_context: str = ""   # Raw context passed to message composer for additional nuance


def synthesize_candidate_status(
    candidate_name: str,
    ashby_record: Optional[dict],
    slack_thread_messages: list[dict],
    email_signals: list[EmailSignal],
    calendar_events: list[CalendarEvent],
) -> StatusSynthesis:
    """
    Synthesize a per-candidate status one-liner from all four sources.

    Args:
        candidate_name:       Full name of the candidate.
        ashby_record:         Ashby submission dict (may be None).
        slack_thread_messages: List of Slack thread message dicts with 'author', 'text', 'timestamp'.
        email_signals:        List of EmailSignal objects from Gmail, newest-first.
        calendar_events:      List of CalendarEvent objects.

    Returns:
        A StatusSynthesis with one_liner, confidence, and flag_for_review.
    """
    first_name = candidate_name.split()[0] if candidate_name else candidate_name

    # ── 1. Google Calendar (highest priority) ────────────────────────────────
    if calendar_events:
        event = calendar_events[0]  # Already sorted: upcoming first, then recent
        stage = _extract_stage_from_event(event.summary)
        date_str = _format_event_date(event.start_time)
        if event.is_upcoming:
            one_liner = f"{stage} is set for {date_str} — excited to see how it goes!"
        else:
            # Past event — we know it happened but don't know the outcome
            one_liner = f"had the {stage} on {date_str} — any feedback on how it went?"

        # Check for soft pass in email/Slack even when calendar exists
        all_text = [s.snippet for s in email_signals] + [m.get("text", "") for m in slack_thread_messages]
        flag = _contains_soft_pass(all_text)

        return StatusSynthesis(
            candidate_name=candidate_name,
            status_source=SOURCE_CALENDAR,
            one_liner=one_liner,
            confidence=CONFIDENCE_HIGH,
            flag_for_review=flag,
            supporting_context=event.summary,
        )

    # ── 2. Gmail (second priority) ────────────────────────────────────────────
    actionable_emails = [s for s in email_signals if s.signal_type in (SIGNAL_ADVANCEMENT, SIGNAL_SCHEDULING, SIGNAL_REJECTION)]
    if actionable_emails:
        top = actionable_emails[0]  # Newest first
        all_text = [s.snippet for s in email_signals] + [m.get("text", "") for m in slack_thread_messages]
        flag = _contains_soft_pass(all_text)

        if top.signal_type == SIGNAL_REJECTION:
            return StatusSynthesis(
                candidate_name=candidate_name,
                status_source=SOURCE_GMAIL,
                one_liner=f"looks like there may have been a pass — wanted to confirm?",
                confidence=CONFIDENCE_MEDIUM,
                flag_for_review=True,
                supporting_context=f"Email: {top.subject} ({_format_event_date(top.date)})",
            )

        if top.signal_type == SIGNAL_SCHEDULING:
            return StatusSynthesis(
                candidate_name=candidate_name,
                status_source=SOURCE_GMAIL,
                one_liner=f"scheduling in progress — any update on next steps?",
                confidence=CONFIDENCE_MEDIUM,
                flag_for_review=flag,
                supporting_context=f"Email: {top.subject} ({_format_event_date(top.date)})",
            )

        # Advancement signal
        date_str = _format_event_date(top.date)
        return StatusSynthesis(
            candidate_name=candidate_name,
            status_source=SOURCE_GMAIL,
            one_liner=f"advanced to the next stage as of {date_str} — any update on where things stand?",
            confidence=CONFIDENCE_MEDIUM,
            flag_for_review=flag,
            supporting_context=f"Email: {top.subject} ({date_str})",
        )

    # ── 3. Slack thread (third priority) ─────────────────────────────────────
    # Filter to non-empty reply messages only (exclude the parent submission)
    replies = [m for m in slack_thread_messages if not m.get("is_parent", False) and m.get("text", "").strip()]
    all_text = [m.get("text", "") for m in slack_thread_messages]
    flag = _contains_soft_pass(all_text)

    if replies:
        # Use the most recent reply as context signal
        latest_reply = replies[-1]
        reply_text = latest_reply.get("text", "")
        reply_date = latest_reply.get("timestamp", "")
        date_str = ""
        if reply_date:
            try:
                dt = datetime.fromisoformat(reply_date)
                date_str = f" as of {_format_event_date(dt)}"
            except Exception:
                pass

        # Detect in-process keywords in thread
        combined = " ".join(all_text).lower()
        if any(kw in combined for kw in ["coding challenge", "hackerrank", "take-home", "homework"]):
            one_liner = f"coding challenge sent{date_str} — any update from {first_name}?"
        elif any(kw in combined for kw in ["tech screen", "technical screen", "phone screen"]):
            one_liner = f"phone/tech screen completed{date_str} — any feedback?"
        elif any(kw in combined for kw in ["onsite", "loop", "final round"]):
            one_liner = f"onsite/loop scheduled{date_str} — any news?"
        else:
            one_liner = f"last activity{date_str} — any update on where things stand?"

        return StatusSynthesis(
            candidate_name=candidate_name,
            status_source=SOURCE_SLACK,
            one_liner=one_liner,
            confidence=CONFIDENCE_MEDIUM,
            flag_for_review=flag,
            supporting_context=reply_text[:200] if reply_text else "",
        )

    # ── 4. Ashby (lowest priority) ────────────────────────────────────────────
    if ashby_record:
        stage = ashby_record.get("pipeline_stage") or ashby_record.get("currentStage") or ""
        days = ashby_record.get("days_in_stage") or ashby_record.get("daysInStage") or 0

        if stage:
            return StatusSynthesis(
                candidate_name=candidate_name,
                status_source=SOURCE_ASHBY,
                one_liner=f"any update on where things stand?",
                confidence=CONFIDENCE_LOW,
                flag_for_review=False,
                supporting_context=f"Ashby stage: {stage} ({days} days)",
            )

    # ── 5. No signal from any source ─────────────────────────────────────────
    return StatusSynthesis(
        candidate_name=candidate_name,
        status_source=SOURCE_NONE,
        one_liner="any update on where things stand here?",
        confidence=CONFIDENCE_LOW,
        flag_for_review=False,
        supporting_context="No recent signal from any source.",
    )
