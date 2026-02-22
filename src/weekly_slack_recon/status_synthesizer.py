"""
Status synthesizer for the Pipeline Status Check workflow.
Uses Claude to reason through all available context — Ashby ATS data,
Google Calendar events, Gmail emails, and Slack thread messages — to produce
a per-candidate status one-liner and confidence level.

Priority (highest → lowest):
  For candidates in Ashby:
    1. Ashby ATS       — structured pipeline stage, interview dates, feedback scores
    2. Google Calendar — a confirmed upcoming/past interview event
    3. Gmail           — emails from the client's domain reveal intros, scheduling, decisions
    4. Slack thread    — the submission thread and any channel mentions

  For Slack-only candidates (no Ashby record):
    1. Google Calendar
    2. Gmail
    3. Slack thread

Claude reads all raw content (email subjects, snippets, Slack message text) and
reasons through what is actually happening. It does NOT rely on pre-classified
signal labels — it interprets the content itself.

Graceful degradation: if no anthropic_api_key is provided, falls back to the
original keyword-matching logic so the workflow still runs without an API key.
"""
from __future__ import annotations

import json
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

# Soft-pass keywords — used in keyword-matching fallback only
_SOFT_PASS_KEYWORDS = [
    "comp mismatch", "compensation mismatch", "salary mismatch",
    "over budget", "overqualified", "underqualified",
    "not the right time", "not a priority", "keeping warm",
    "table this", "hold off", "put a pin",
    "concerned about", "hesitant", "on the fence",
]

_SYNTHESIS_SYSTEM_PROMPT = """\
You are an AI assistant helping a recruiter (DK, David Kimball at Candidate Labs) \
track the status of candidates submitted to client companies.

Your job: given all available context about a candidate, produce a concise, \
specific status one-liner for a client-facing check-in message.

PRIORITY ORDER:
{priority_instruction}

INSTRUCTIONS:
- Today is {today}. Use this to resolve any relative dates in messages \
("next Friday", "this Thursday", "tomorrow" → actual calendar dates).
- Read all raw content carefully — email subjects, snippets, and Slack message \
text — and reason through what is actually happening for this candidate. \
Do NOT rely on pre-assigned labels; read the content itself.
- For emails: determine if the email is an intro, scheduling confirmation, \
candidate replying with availability, a pass, or advancement — based on what \
it actually says.
- For Slack messages: distinguish between DK's own messages (he may be asking \
for an update) and client or candidate replies (actual signals).

RULES FOR THE ONE-LINER:
- Lead with the most specific fact you can state with confidence and a date.
- If the most recent signal is an intro email → "introduced [date], any updates?"
- If an interview/screen is scheduled in the future → state the date and express optimism.
- If an interview/screen was scheduled and the date is now past and you have \
no outcome signal → "was scheduled for [stage] on [date] — how did it go?"
- If there is clear advancement signal → "moved forward to [stage] as of [date]"
- If a Slack message contains relative dates, resolve them to real dates using today's date.
- NEVER use vague phrases like "recently", "mid-February", "in progress", \
or "underway" when you have a specific date available.
- Flag for review (flag_for_review: true) if any soft-pass language appears \
(comp mismatch, not a priority, hesitant, keeping warm, hold off, etc.)

OUTPUT: Return ONLY a JSON object — no preamble, no explanation:
{{
  "one_liner": "...",
  "confidence": "high|medium|low",
  "status_source": "ashby|calendar|gmail|slack|none",
  "flag_for_review": true|false,
  "supporting_context": "one-line summary of the key evidence used"
}}"""


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
    anthropic_api_key: Optional[str] = None,
    model: str = "claude-haiku-4-5-20251001",
    today: Optional[datetime] = None,
) -> StatusSynthesis:
    """
    Synthesize a per-candidate status one-liner from all available sources.

    When anthropic_api_key is provided, uses Claude to reason through the raw
    context (Ashby data, Slack messages, Gmail emails, Calendar events).
    Falls back to keyword matching if no API key is set.

    Args:
        candidate_name:        Full name of the candidate.
        ashby_record:          Ashby submission dict (may be None).
        slack_thread_messages: List of Slack thread message dicts.
        email_signals:         List of EmailSignal objects, newest-first.
        calendar_events:       List of CalendarEvent objects.
        anthropic_api_key:     Anthropic API key; if None, uses keyword fallback.
        model:                 Claude model to use for synthesis.
        today:                 Current datetime (defaults to UTC now).

    Returns:
        A StatusSynthesis with one_liner, confidence, and flag_for_review.
    """
    if today is None:
        today = datetime.now(tz=timezone.utc)

    if anthropic_api_key:
        return _synthesize_with_claude(
            candidate_name=candidate_name,
            ashby_record=ashby_record,
            slack_thread_messages=slack_thread_messages,
            email_signals=email_signals,
            calendar_events=calendar_events,
            anthropic_api_key=anthropic_api_key,
            model=model,
            today=today,
        )

    # ── Keyword-matching fallback (no API key) ────────────────────────────────
    return _synthesize_with_keywords(
        candidate_name=candidate_name,
        ashby_record=ashby_record,
        slack_thread_messages=slack_thread_messages,
        email_signals=email_signals,
        calendar_events=calendar_events,
    )


# ── Claude-powered synthesis ──────────────────────────────────────────────────

def _synthesize_with_claude(
    candidate_name: str,
    ashby_record: Optional[dict],
    slack_thread_messages: list[dict],
    email_signals: list[EmailSignal],
    calendar_events: list[CalendarEvent],
    anthropic_api_key: str,
    model: str,
    today: datetime,
) -> StatusSynthesis:
    """Call Claude with all available raw context to reason about candidate status."""
    import anthropic

    has_ashby = bool(ashby_record)
    today_str = today.strftime("%A, %B %d, %Y")  # e.g. "Saturday, February 22, 2026"

    if has_ashby:
        priority_instruction = (
            "1. Ashby ATS (highest — the client is running a formal process)\n"
            "2. Google Calendar — confirms actual interview scheduling\n"
            "3. Gmail — emails from the client domain reveal intros, scheduling, outcomes\n"
            "4. Slack thread (lowest — often goes stale quickly)"
        )
    else:
        priority_instruction = (
            "1. Google Calendar (highest — confirms actual interview scheduling)\n"
            "2. Gmail — emails from the client domain reveal intros, scheduling, outcomes\n"
            "3. Slack thread (lowest — often goes stale quickly)"
        )

    system = _SYNTHESIS_SYSTEM_PROMPT.format(
        priority_instruction=priority_instruction,
        today=today_str,
    )

    # ── Build structured context for Claude ───────────────────────────────────
    context: dict = {"candidate_name": candidate_name, "today": today_str}

    if has_ashby:
        context["ashby"] = {
            "pipeline_stage": ashby_record.get("pipeline_stage"),
            "decision_status": ashby_record.get("decision_status"),
            "stage_progress": ashby_record.get("stage_progress"),
            "days_in_stage": ashby_record.get("days_in_stage"),
            "needs_scheduling": ashby_record.get("needs_scheduling"),
            "latest_recommendation": ashby_record.get("latest_recommendation"),
            "latest_feedback_author": ashby_record.get("latest_feedback_author"),
            "latest_feedback_date": ashby_record.get("latest_feedback_date"),
            "current_stage_date": ashby_record.get("current_stage_date"),
            "current_stage_avg_score": ashby_record.get("current_stage_avg_score"),
            "current_stage_interviews": ashby_record.get("current_stage_interviews"),
            "interview_history_summary": ashby_record.get("interview_history_summary"),
            "interview_events": ashby_record.get("interview_events") or [],
        }

    if calendar_events:
        context["calendar_events"] = [
            {
                "summary": e.summary,
                "start_time": e.start_time.strftime("%Y-%m-%d %H:%M UTC"),
                "is_upcoming": e.is_upcoming,
            }
            for e in calendar_events
        ]

    if email_signals:
        context["gmail_emails"] = [
            {
                "subject": e.subject,
                "sender": e.sender,
                "date": e.date.strftime("%Y-%m-%d"),
                "snippet": e.snippet,
            }
            for e in email_signals
        ]

    if slack_thread_messages:
        context["slack_thread"] = slack_thread_messages

    user_content = (
        f"Synthesize the status for this candidate:\n\n"
        f"{json.dumps(context, indent=2, default=str)}"
    )

    try:
        client = anthropic.Anthropic(api_key=anthropic_api_key)
        response = client.messages.create(
            model=model,
            max_tokens=300,
            system=system,
            messages=[{"role": "user", "content": user_content}],
        )
        raw = response.content[0].text.strip()

        # Strip code fences if present
        if raw.startswith("```"):
            lines = raw.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            raw = "\n".join(lines).strip()

        parsed = json.loads(raw)
        return StatusSynthesis(
            candidate_name=candidate_name,
            status_source=parsed.get("status_source", SOURCE_NONE),
            one_liner=parsed.get("one_liner", "any update on where things stand?"),
            confidence=parsed.get("confidence", CONFIDENCE_LOW),
            flag_for_review=bool(parsed.get("flag_for_review", False)),
            supporting_context=parsed.get("supporting_context", ""),
        )

    except Exception as e:
        print(f"[SYNTHESIZER] Claude error for {candidate_name}: {e} — falling back to keywords")
        return _synthesize_with_keywords(
            candidate_name=candidate_name,
            ashby_record=ashby_record,
            slack_thread_messages=slack_thread_messages,
            email_signals=email_signals,
            calendar_events=calendar_events,
        )


# ── Keyword-matching fallback ─────────────────────────────────────────────────

def _contains_soft_pass(texts: list[str]) -> bool:
    combined = " ".join(texts).lower()
    return any(kw in combined for kw in _SOFT_PASS_KEYWORDS)


def _format_event_date(dt: datetime) -> str:
    return f"{dt.month}/{dt.day}"


def _extract_stage_from_event(summary: str) -> str:
    summary_lower = summary.lower()
    for stage in ["onsite", "technical", "tech screen", "coding", "loop", "final", "intro", "phone"]:
        if stage in summary_lower:
            return stage
    return "interview"


def _synthesize_with_keywords(
    candidate_name: str,
    ashby_record: Optional[dict],
    slack_thread_messages: list[dict],
    email_signals: list[EmailSignal],
    calendar_events: list[CalendarEvent],
) -> StatusSynthesis:
    """Original keyword-matching synthesis. Used as fallback when Claude is unavailable."""
    first_name = candidate_name.split()[0] if candidate_name else candidate_name

    # ── 1. Google Calendar ────────────────────────────────────────────────────
    if calendar_events:
        event = calendar_events[0]
        stage = _extract_stage_from_event(event.summary)
        date_str = _format_event_date(event.start_time)
        if event.is_upcoming:
            one_liner = f"{stage} is set for {date_str} — excited to see how it goes!"
        else:
            one_liner = f"had the {stage} on {date_str} — any feedback on how it went?"

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

    # ── 2. Gmail ──────────────────────────────────────────────────────────────
    actionable_emails = [s for s in email_signals if s.signal_type in (SIGNAL_ADVANCEMENT, SIGNAL_SCHEDULING, SIGNAL_REJECTION)]
    if actionable_emails:
        top = actionable_emails[0]
        all_text = [s.snippet for s in email_signals] + [m.get("text", "") for m in slack_thread_messages]
        flag = _contains_soft_pass(all_text)

        if top.signal_type == SIGNAL_REJECTION:
            return StatusSynthesis(
                candidate_name=candidate_name,
                status_source=SOURCE_GMAIL,
                one_liner="looks like there may have been a pass — wanted to confirm?",
                confidence=CONFIDENCE_MEDIUM,
                flag_for_review=True,
                supporting_context=f"Email: {top.subject} ({_format_event_date(top.date)})",
            )

        if top.signal_type == SIGNAL_SCHEDULING:
            return StatusSynthesis(
                candidate_name=candidate_name,
                status_source=SOURCE_GMAIL,
                one_liner="scheduling in progress — any update on next steps?",
                confidence=CONFIDENCE_MEDIUM,
                flag_for_review=flag,
                supporting_context=f"Email: {top.subject} ({_format_event_date(top.date)})",
            )

        date_str = _format_event_date(top.date)
        return StatusSynthesis(
            candidate_name=candidate_name,
            status_source=SOURCE_GMAIL,
            one_liner=f"advanced to the next stage as of {date_str} — any update on where things stand?",
            confidence=CONFIDENCE_MEDIUM,
            flag_for_review=flag,
            supporting_context=f"Email: {top.subject} ({date_str})",
        )

    # ── 3. Slack thread ───────────────────────────────────────────────────────
    replies = [m for m in slack_thread_messages if not m.get("is_parent", False) and m.get("text", "").strip()]
    all_text = [m.get("text", "") for m in slack_thread_messages]
    flag = _contains_soft_pass(all_text)

    if replies:
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

    # ── 4. Ashby ──────────────────────────────────────────────────────────────
    if ashby_record:
        stage = ashby_record.get("pipeline_stage") or ashby_record.get("currentStage") or ""
        days = ashby_record.get("days_in_stage") or ashby_record.get("daysInStage") or 0

        if stage:
            return StatusSynthesis(
                candidate_name=candidate_name,
                status_source=SOURCE_ASHBY,
                one_liner="any update on where things stand?",
                confidence=CONFIDENCE_LOW,
                flag_for_review=False,
                supporting_context=f"Ashby stage: {stage} ({days} days)",
            )

    # ── 5. No signal ──────────────────────────────────────────────────────────
    return StatusSynthesis(
        candidate_name=candidate_name,
        status_source=SOURCE_NONE,
        one_liner="any update on where things stand here?",
        confidence=CONFIDENCE_LOW,
        flag_for_review=False,
        supporting_context="No recent signal from any source.",
    )
