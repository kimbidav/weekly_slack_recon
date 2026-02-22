"""
Message composer for the Pipeline Status Check workflow.
Uses Claude to draft professional, client-facing check-in messages
for each active client based on synthesized candidate status data.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import anthropic

from .status_synthesizer import StatusSynthesis


SYSTEM_PROMPT = """You are a professional recruiter named DK (David Kimball) at Candidate Labs.
You are composing weekly check-in messages to send to client hiring teams in Slack Connect channels.

TONE REQUIREMENTS:
- Professional but warm — you're messaging the client's hiring team directly
- Concise — the client should scan the message in 15 seconds
- Positive framing — celebrate momentum, ask gently about stale items
- No internal jargon — no Ashby stage names, days-in-stage counts, or recruiter shorthand

MESSAGE FORMAT:
Hey team! Quick check-in on my candidates:
– {Candidate Name} — {status one-liner}
– {Candidate Name} — {status one-liner}
{warm 1-sentence closing}
-- by Claude <3

ONE-LINER RULES:
- The one_liner field has already been reasoned from source data (Ashby, Gmail, Slack, Calendar).
  Use it as the authoritative basis for each candidate's line — do not second-guess or soften it.
- 1–2 sentences maximum per candidate
- You may lightly reword for flow and tone, but preserve all specific dates and facts
- Do NOT include candidates flagged for review unless explicitly included
- NEVER state uncertain information as fact — if the one_liner asks a question, keep it as a question

You will receive a JSON object with client info and candidate statuses.
Return ONLY the formatted message, no preamble or explanation."""


@dataclass
class DraftMessage:
    """A drafted check-in message for one client channel."""
    draft_id: str
    client_name: str
    channel_id: str
    channel_name: str
    message_text: str          # The full drafted message
    candidates: list[dict]     # List of candidate status dicts for UI display
    status: str = "pending"    # pending / approved / skipped


def compose_checkin_message(
    client_name: str,
    candidate_syntheses: list[StatusSynthesis],
    model: str = "claude-sonnet-4-6",
    anthropic_api_key: Optional[str] = None,
) -> str:
    """
    Call Claude to draft a single client check-in message.

    Args:
        client_name:          The client company name (for context).
        candidate_syntheses:  List of StatusSynthesis objects for active candidates.
        model:                Claude model to use.
        anthropic_api_key:    Anthropic API key (uses env var if not provided).

    Returns:
        The drafted message text.
    """
    # Filter out flagged-for-review candidates
    active = [s for s in candidate_syntheses if not s.flag_for_review]
    if not active:
        return ""

    # Build the user prompt as structured JSON context
    candidates_ctx = []
    for s in active:
        candidates_ctx.append({
            "name": s.candidate_name,
            "one_liner": s.one_liner,
            "confidence": s.confidence,
            "source": s.status_source,
            "supporting_context": s.supporting_context,
        })

    import json
    user_content = json.dumps({
        "client_name": client_name,
        "candidates": candidates_ctx,
    }, indent=2)

    client = anthropic.Anthropic(api_key=anthropic_api_key) if anthropic_api_key else anthropic.Anthropic()

    response = client.messages.create(
        model=model,
        max_tokens=600,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_content}],
    )

    return response.content[0].text.strip()
