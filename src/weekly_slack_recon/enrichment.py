"""LLM-powered enrichment for candidate submissions.

Uses Claude to analyze gathered Slack context and produce a concise
status summary for each candidate.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import anthropic

from .config import Config
from .context_gatherer import CandidateContext, gather_context_batch
from .logic import CandidateSubmission
from .slack_client import SlackAPI


SYSTEM_PROMPT = """\
You are an assistant that analyzes recruiting pipeline data for a staffing firm called Candidate Labs.
You are given context about a candidate who was submitted to a client company via Slack.
The context includes the original submission thread, any channel messages mentioning the candidate by name, and threads on those mentions.

Your job is to write a concise bullet-point summary so the user doesn't have to read through all the individual threads to know what's going on with this candidate.

Output a JSON object with exactly these fields:
- "ai_summary": A concise bullet-point summary using this format:
  • Each bullet starts with "• "
  • 2-5 bullets covering the key developments in chronological order
  • Reference specific details — dates, who said what, feedback, next steps, interviews, offers, rejections
  • Be specific and factual, do not speculate
  • If there's nothing beyond the initial submission, just say "• No activity beyond initial submission"

Return ONLY the JSON object, no other text."""


@dataclass
class EnrichmentResult:
    """Result of LLM enrichment for one candidate."""
    candidate_name: str
    linkedin_url: str
    channel_name: str
    ai_summary: str
    enriched_at: str  # ISO format
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidate_name": self.candidate_name,
            "linkedin_url": self.linkedin_url,
            "channel_name": self.channel_name,
            "ai_summary": self.ai_summary,
            "enriched_at": self.enriched_at,
            "error": self.error,
        }


def _call_claude(
    client: anthropic.Anthropic,
    cfg: Config,
    context: CandidateContext,
) -> EnrichmentResult:
    """Call Claude for a single candidate's context."""
    now_iso = datetime.now(tz=timezone.utc).isoformat()
    prompt_text = context.to_prompt_text()

    try:
        message = client.messages.create(
            model=cfg.enrichment_model,
            max_tokens=cfg.enrichment_max_tokens,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": f"Analyze this candidate's current status:\n\n{prompt_text}",
                }
            ],
        )

        # Extract the text content
        response_text = ""
        for block in message.content:
            if block.type == "text":
                response_text += block.text

        # Parse JSON from response
        # Handle cases where Claude wraps in ```json ... ```
        cleaned = response_text.strip()
        if cleaned.startswith("```"):
            # Remove code fence
            lines = cleaned.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            cleaned = "\n".join(lines).strip()

        # Try to parse as JSON first; fall back to using raw text as summary
        try:
            parsed = json.loads(cleaned)
            summary = parsed.get("ai_summary", cleaned)
        except json.JSONDecodeError:
            # Claude returned plain text instead of JSON — just use it directly
            summary = cleaned

        return EnrichmentResult(
            candidate_name=context.candidate_name,
            linkedin_url=context.linkedin_url,
            channel_name=context.channel_name,
            ai_summary=summary or "No details available.",
            enriched_at=now_iso,
        )

    except anthropic.APIError as e:
        print(f"[ENRICH] Claude API error for {context.candidate_name}: {e}")
        return EnrichmentResult(
            candidate_name=context.candidate_name,
            linkedin_url=context.linkedin_url,
            channel_name=context.channel_name,
            ai_summary=f"Error: {str(e)[:150]}",
            enriched_at=now_iso,
            error=str(e)[:200],
        )

    except Exception as e:
        print(f"[ENRICH] Unexpected error for {context.candidate_name}: {e}")
        return EnrichmentResult(
            candidate_name=context.candidate_name,
            linkedin_url=context.linkedin_url,
            channel_name=context.channel_name,
            ai_summary=f"Error: {str(e)[:150]}",
            enriched_at=now_iso,
            error=str(e)[:200],
        )


def enrich_submissions(
    cfg: Config,
    slack: SlackAPI,
    submissions: List[CandidateSubmission],
    progress_callback=None,
) -> List[EnrichmentResult]:
    """Run full enrichment pipeline: gather context then call Claude for each candidate.

    Args:
        cfg: Configuration (must have anthropic_api_key set)
        slack: Slack API client
        submissions: Submissions to enrich
        progress_callback: Optional callable(phase, current, total, detail)
            phase is "gathering" or "analyzing"

    Returns:
        List of EnrichmentResult, one per submission
    """
    if not cfg.anthropic_api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY must be set in environment or .env file "
            "to use LLM enrichment."
        )

    client = anthropic.Anthropic(api_key=cfg.anthropic_api_key)

    # Phase 1: Gather context from Slack
    def gather_progress(current, total, name):
        if progress_callback:
            progress_callback("gathering", current, total, name)

    contexts = gather_context_batch(cfg, slack, submissions, progress_callback=gather_progress)

    # Phase 2: Call Claude for each candidate
    results: List[EnrichmentResult] = []
    for i, ctx in enumerate(contexts):
        if progress_callback:
            progress_callback("analyzing", i, len(contexts), ctx.candidate_name)

        result = _call_claude(client, cfg, ctx)
        results.append(result)

    if progress_callback:
        progress_callback("complete", len(contexts), len(contexts), "done")

    return results
