from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Iterable, List, Dict, Any
import csv
import io
import json

from rich.console import Console
from rich.table import Table

from .logic import CandidateSubmission
from .status_rules import StatusCategory


def group_by_channel(submissions: Iterable[CandidateSubmission]) -> Dict[str, List[CandidateSubmission]]:
    grouped: Dict[str, List[CandidateSubmission]] = defaultdict(list)
    for s in submissions:
        grouped[s.channel_name].append(s)
    # Sort by channel name for stable output
    return dict(sorted(grouped.items(), key=lambda kv: kv[0].lower()))


def print_report(submissions: List[CandidateSubmission]) -> None:
    console = Console()

    if not submissions:
        console.print("[bold yellow]No candidate submissions found in the lookback window.[/bold yellow]")
        return

    grouped = group_by_channel(submissions)

    console.print("[bold underline]Weekly Slack Pipeline Reconciliation[/bold underline]")
    console.print()

    for channel_name, items in grouped.items():
        console.print(f"[bold cyan][{channel_name}][/bold cyan]")

        closed = [s for s in items if s.status == StatusCategory.CLOSED]
        in_process_explicit = [s for s in items if s.status == StatusCategory.IN_PROCESS_EXPLICIT]
        in_process_unclear = [s for s in items if s.status == StatusCategory.IN_PROCESS_UNCLEAR]

        def _render_section(title: str, rows: List[CandidateSubmission], highlight_followups: bool = False) -> None:
            console.print(f"  [bold]{title}[/bold]")
            if not rows:
                console.print("    (none)")
                return
            for s in rows:
                suffix_parts: List[str] = []
                if s.status == StatusCategory.CLOSED and s.status_reason:
                    suffix_parts.append(f"{s.status_reason}")
                if highlight_followups and s.needs_followup:
                    suffix_parts.append(f"needs follow-up (submitted {s.days_since_submission} days ago)")
                elif not highlight_followups and s.status == StatusCategory.IN_PROCESS_UNCLEAR:
                    suffix_parts.append(f"submitted {s.days_since_submission} days ago")

                suffix = " ".join(f"({p})" for p in suffix_parts) if suffix_parts else ""
                console.print(f"    - {s.candidate_name} {suffix}")

        _render_section("CLOSED", closed)
        _render_section("IN PROCESS  explicit", in_process_explicit)
        _render_section("IN PROCESS  unclear (needs follow-up)", in_process_unclear, highlight_followups=True)
        console.print()


def write_markdown(submissions: List[CandidateSubmission], path: str, generated_at: datetime) -> None:
    grouped = group_by_channel(submissions)

    lines: List[str] = []
    lines.append("# Weekly Slack Pipeline Reconciliation")
    lines.append("")
    lines.append(f"Generated at: {generated_at.isoformat()}")
    lines.append("")

    for channel_name, items in grouped.items():
        lines.append(f"## {channel_name}")
        lines.append("")

        def _section_md(title: str, rows: List[CandidateSubmission], highlight_followups: bool = False) -> None:
            lines.append(f"### {title}")
            if not rows:
                lines.append("- (none)")
                lines.append("")
                return
            for s in rows:
                suffix_parts: List[str] = []
                if s.status == StatusCategory.CLOSED and s.status_reason:
                    suffix_parts.append(s.status_reason)
                if highlight_followups and s.needs_followup:
                    suffix_parts.append(f"needs follow-up (submitted {s.days_since_submission} days ago)")
                elif not highlight_followups and s.status == StatusCategory.IN_PROCESS_UNCLEAR:
                    suffix_parts.append(f"submitted {s.days_since_submission} days ago")
                suffix = " ".join(f"({p})" for p in suffix_parts) if suffix_parts else ""
                lines.append(f"- {s.candidate_name} {suffix}")
            lines.append("")

        closed = [s for s in items if s.status == StatusCategory.CLOSED]
        in_process_explicit = [s for s in items if s.status == StatusCategory.IN_PROCESS_EXPLICIT]
        in_process_unclear = [s for s in items if s.status == StatusCategory.IN_PROCESS_UNCLEAR]

        _section_md("CLOSED", closed)
        _section_md("IN PROCESS  explicit", in_process_explicit)
        _section_md("IN PROCESS  unclear (needs follow-up)", in_process_unclear, highlight_followups=True)

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def write_csv(submissions: List[CandidateSubmission], path: str, generated_at: datetime) -> None:
    """Write submissions to CSV file."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Channel",
            "Candidate Name",
            "LinkedIn URL",
            "Status",
            "Status Reason",
            "Submitted At",
            "Days Since Submission",
            "Needs Follow-up",
        ])
        for s in submissions:
            writer.writerow([
                s.channel_name,
                s.candidate_name,
                s.linkedin_url,
                s.status,
                s.status_reason or "",
                s.submitted_at.isoformat(),
                s.days_since_submission,
                "Yes" if s.needs_followup else "No",
            ])


def generate_csv_string(submissions: List[CandidateSubmission]) -> str:
    """Generate CSV content as a string (for download)."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Channel",
        "Candidate Name",
        "LinkedIn URL",
        "Status",
        "Status Reason",
        "Submitted At",
        "Days Since Submission",
        "Needs Follow-up",
    ])
    for s in submissions:
        writer.writerow([
            s.channel_name,
            s.candidate_name,
            s.linkedin_url,
            s.status,
            s.status_reason or "",
            s.submitted_at.isoformat(),
            s.days_since_submission,
            "Yes" if s.needs_followup else "No",
        ])
    return output.getvalue()


def write_json(submissions: List[CandidateSubmission], path: str, generated_at: datetime) -> None:
    """Write submissions to JSON file for dashboard consumption."""
    data: Dict[str, Any] = {
        "generated_at": generated_at.isoformat(),
        "submissions": []
    }
    
    for s in submissions:
        entry = {
            "candidate_name": s.candidate_name,
            "linkedin_url": s.linkedin_url,
            "channel_name": s.channel_name,
            "channel_id": s.channel_id,
            "submitted_at": s.submitted_at.isoformat(),
            "status": s.status,
            "status_reason": s.status_reason,
            "days_since_submission": s.days_since_submission,
            "needs_followup": s.needs_followup,
            "slack_url": s.slack_url,
            # AI enrichment fields (populated by enrichment step)
            "ai_summary": getattr(s, 'ai_summary', None),
            "ai_enriched_at": getattr(s, 'ai_enriched_at', None),
        }
        data["submissions"].append(entry)
    
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def generate_followup_snippets(submissions: List[CandidateSubmission]) -> Dict[str, str]:
    """Return per-channel Slack-ready follow-up message text for unclear candidates needing follow-up."""

    grouped = group_by_channel([s for s in submissions if s.needs_followup])
    snippets: Dict[str, str] = {}

    for channel_name, items in grouped.items():
        if not items:
            continue
        lines: List[str] = []
        lines.append("Quick check on a few candidates I haven't seen updates on yet:")
        for s in items:
            lines.append(f"– {s.candidate_name}")
        lines.append("")
        lines.append("Appreciate any updates when you get a moment 🙏")
        snippets[channel_name] = "\n".join(lines)

    return snippets
