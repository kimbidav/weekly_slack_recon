"""
Import and normalize candidates from an Ashby JSON export into the unified
submission format used by the Weekly Slack Recon dashboard.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def find_latest_ashby_export(path: str) -> str:
    """
    Given a path that is either a JSON file or a directory, return the path to
    the JSON file to use. If a directory is given, returns the most recently
    modified .json file in that directory.

    Raises FileNotFoundError if nothing suitable is found.
    """
    p = Path(path)
    if p.is_file():
        return str(p)
    if p.is_dir():
        json_files = sorted(p.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
        if not json_files:
            raise FileNotFoundError(f"No JSON files found in directory: {path}")
        return str(json_files[0])
    raise FileNotFoundError(f"Path does not exist: {path}")


_DK_NAMES: set = {"david", "dk", "david kimball", "david cl"}


def _is_dk_credited(candidate: Dict[str, Any]) -> bool:
    """Return True if this candidate is credited to David Kimball / DK."""
    credited = (candidate.get("creditedTo") or "").strip().lower()
    return credited in _DK_NAMES


def load_ashby_export(json_path: str) -> List[Dict[str, Any]]:
    """
    Load an Ashby JSON export and return a list of normalized submission dicts
    that are compatible with the weekly_slack_reconciliation.json format.

    The Ashby export is produced by the separate Ashby Automation tool and has
    the structure: { companies: [...], jobs: [...], candidates: [...] }

    Candidates credited to David Kimball / DK are excluded.
    """
    path = Path(json_path)
    if not path.exists():
        raise FileNotFoundError(f"Ashby JSON export not found: {json_path}")

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    jobs: Dict[str, Dict] = {j["id"]: j for j in data.get("jobs", [])}
    candidates = data.get("candidates", [])

    now = datetime.now(tz=timezone.utc)
    normalized: List[Dict[str, Any]] = []

    for candidate in candidates:
        # Keep only candidates credited to DK
        if not _is_dk_credited(candidate):
            continue

        job = jobs.get(candidate.get("jobId", ""), {})

        # Parse last activity timestamp
        last_activity_raw = candidate.get("lastActivityAt", "")
        try:
            last_activity_dt = datetime.fromisoformat(
                last_activity_raw.replace("Z", "+00:00")
            )
        except (ValueError, AttributeError):
            last_activity_dt = now

        days_since = max(0, (now - last_activity_dt).days)

        # Normalize LinkedIn URL
        linkedin_url = (
            candidate.get("linkedInUrl")
            or candidate.get("linkedinUrl")
            or None
        )

        # Company name: orgName is the client org (e.g. "Agave", "Canals"),
        # matching how the Ashby CSV exporter resolves it.
        company_name = candidate.get("orgName") or None

        normalized.append({
            # Source marker
            "source": "ashby",

            # ── Common fields ──────────────────────────────────────────────
            "candidate_name": candidate.get("name") or "Unknown",
            "linkedin_url": linkedin_url,
            "email": candidate.get("primaryEmailAddress") or candidate.get("email"),
            "submitted_at": last_activity_dt.isoformat(),
            "days_since_submission": days_since,
            "status": _map_ashby_status(candidate),
            "status_reason": (
                candidate.get("pipelineStage")
                or candidate.get("currentStage")
                or None
            ),
            "needs_followup": bool(candidate.get("needsScheduling", False)),
            "ai_summary": None,
            "ai_enriched_at": None,

            # ── Slack-specific (always null for Ashby candidates) ──────────
            "channel_name": None,
            "channel_id": None,
            "slack_url": None,

            # ── Ashby-specific fields ──────────────────────────────────────
            "company_name": company_name,
            "job_title": job.get("title") or None,
            "pipeline_stage": candidate.get("pipelineStage") or None,
            "stage_progress": candidate.get("stageProgress") or None,
            "days_in_stage": candidate.get("daysInStage"),
            "needs_scheduling": candidate.get("needsScheduling"),
            "latest_recommendation": candidate.get("latestOverallRecommendation") or None,
            "latest_feedback_author": candidate.get("latestFeedbackAuthor") or None,
            "ashby_application_id": candidate.get("applicationId") or None,
            "ashby_candidate_id": candidate.get("id") or None,
            "credited_to": candidate.get("creditedTo") or None,
        })

    return normalized


def merge_ashby_into_submissions(
    existing: List[Dict[str, Any]],
    ashby_candidates: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Merge Ashby candidates into an existing submissions list.

    - Removes any previously imported Ashby candidates (clean re-import)
    - Appends the new Ashby candidates
    - Flags Slack candidates whose LinkedIn URL also appears in Ashby (and vice-versa)
      so the dashboard can show a cross-source badge
    """

    def _normalize_url(url: Optional[str]) -> str:
        if not url:
            return ""
        return url.strip().rstrip("/").lower()

    # Build LinkedIn URL sets for each source
    ashby_urls = {
        _normalize_url(c.get("linkedin_url"))
        for c in ashby_candidates
        if c.get("linkedin_url")
    }

    # Keep only Slack candidates (drop any stale Ashby imports)
    slack_candidates = [
        s for s in existing if s.get("source", "slack") != "ashby"
    ]

    slack_urls = {
        _normalize_url(s.get("linkedin_url"))
        for s in slack_candidates
        if s.get("linkedin_url")
    }

    # Mark Slack candidates that also appear in Ashby
    for s in slack_candidates:
        url = _normalize_url(s.get("linkedin_url"))
        s["also_in_ashby"] = bool(url and url in ashby_urls)

    # Mark Ashby candidates that also appear in Slack
    for c in ashby_candidates:
        url = _normalize_url(c.get("linkedin_url"))
        c["also_in_slack"] = bool(url and url in slack_urls)

    return slack_candidates + ashby_candidates


def _map_ashby_status(candidate: Dict[str, Any]) -> str:
    """
    Map Ashby pipeline state to a status string compatible with the
    Slack Recon dashboard's status vocabulary.

    Returns one of: "CLOSED", "IN PROCESS — explicit", "IN PROCESS — unclear"
    """
    stage = (candidate.get("currentStage") or "").lower()
    stage_type = (candidate.get("stageType") or "").lower()
    pipeline = (candidate.get("pipelineStage") or "").lower()

    # Rejection / closed signals
    rejection_keywords = {"reject", "declined", "archived", "withdraw", "no hire"}
    if any(k in stage for k in rejection_keywords) or any(
        k in pipeline for k in rejection_keywords
    ):
        return "CLOSED"

    # Offer or hired — still "in process" from a tracking standpoint
    if stage_type in ("offer", "hired") or "offer" in stage or "hired" in stage:
        return "IN PROCESS — explicit"

    # Any explicit interview pipeline stage = in process with clarity
    if candidate.get("pipelineStage"):
        return "IN PROCESS — explicit"

    # Has a current decision stage but no pipeline stage
    if candidate.get("currentStage"):
        return "IN PROCESS — unclear"

    return "IN PROCESS — unclear"
