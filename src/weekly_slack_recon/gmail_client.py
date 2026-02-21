"""
Gmail API client for the Pipeline Status Check workflow.
Searches for emails involving a candidate where DK is in the To or CC field,
returning structured EmailSignal objects ranked by recency.
"""
from __future__ import annotations

import base64
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from .google_auth_helper import get_credentials

# OAuth scopes needed
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

# Signal type labels
SIGNAL_ADVANCEMENT = "advancement"
SIGNAL_SCHEDULING = "scheduling"
SIGNAL_REJECTION = "rejection"
SIGNAL_OTHER = "other"

_ADVANCEMENT_KEYWORDS = [
    "move forward", "moving forward", "advance", "advancing", "next round",
    "next step", "next stage", "proceed", "interview", "onsite", "loop",
    "technical screen", "coding challenge", "hackerrank", "take-home",
]
_REJECTION_KEYWORDS = [
    "pass", "not moving forward", "not a fit", "not the right fit",
    "decline", "declined", "rejected", "rejection", "unfortunately",
    "decided not to", "going a different direction",
]
_SCHEDULING_KEYWORDS = [
    "calendar invite", "calendar link", "schedule", "scheduling",
    "book a time", "availability", "calendly", "zoom link",
    "google meet", "teams link",
]


def _classify_signal(subject: str, snippet: str) -> str:
    """Classify an email signal based on subject + snippet text."""
    combined = (subject + " " + snippet).lower()
    for kw in _REJECTION_KEYWORDS:
        if kw in combined:
            return SIGNAL_REJECTION
    for kw in _SCHEDULING_KEYWORDS:
        if kw in combined:
            return SIGNAL_SCHEDULING
    for kw in _ADVANCEMENT_KEYWORDS:
        if kw in combined:
            return SIGNAL_ADVANCEMENT
    return SIGNAL_OTHER


def _build_name_variants(candidate_name: str) -> list[str]:
    """Return search-friendly name variants from a full name."""
    parts = candidate_name.strip().split()
    if not parts:
        return [candidate_name]
    variants = [candidate_name]
    first = parts[0]
    variants.append(first)
    if len(parts) >= 2:
        last = parts[-1]
        variants.append(last)
        # First name + last initial
        variants.append(f"{first} {last[0]}")
    return list(dict.fromkeys(variants))  # deduplicate, preserve order


@dataclass
class EmailSignal:
    """A single email that's relevant to a candidate's status."""
    message_id: str
    subject: str
    sender: str
    date: datetime
    snippet: str
    signal_type: str  # advancement / scheduling / rejection / other


class GmailClient:
    """Searches Gmail for candidate-related emails where DK is To/CC."""

    def __init__(self, credentials_path: str, token_path: str):
        creds = get_credentials(credentials_path, token_path, SCOPES)
        self._service = build("gmail", "v1", credentials=creds, cache_discovery=False)

    def search_emails(
        self,
        candidate_name: str,
        client_name: str = "",
        lookback_days: int = 60,
        max_results: int = 20,
    ) -> list[EmailSignal]:
        """
        Search for emails mentioning a candidate where DK is in To or CC.

        Args:
            candidate_name: Full name of the candidate.
            client_name:    Client company name (used to narrow search).
            lookback_days:  How far back to search (default 60 days).
            max_results:    Max emails to return per query.

        Returns:
            List of EmailSignal sorted newest-first.
        """
        name_variants = _build_name_variants(candidate_name)
        # Use the most specific variant (full name first)
        primary_query = f'"{name_variants[0]}"'
        if client_name:
            # Also try with just first name + client name
            first = name_variants[0].split()[0] if name_variants[0] else ""
            query = (
                f'({primary_query} OR "{first}") '
                f'newer_than:{lookback_days}d'
            )
        else:
            query = f'{primary_query} newer_than:{lookback_days}d'

        signals: list[EmailSignal] = []
        try:
            results = self._execute_with_backoff(
                self._service.users().messages().list(
                    userId="me",
                    q=query,
                    maxResults=max_results,
                )
            )
            messages = results.get("messages", [])
            for msg_ref in messages:
                signal = self._fetch_signal(msg_ref["id"])
                if signal:
                    signals.append(signal)
        except HttpError as e:
            print(f"[GMAIL] Search error for '{candidate_name}': {e}")

        # Sort newest first
        signals.sort(key=lambda s: s.date, reverse=True)
        return signals

    def _fetch_signal(self, message_id: str) -> Optional[EmailSignal]:
        """Fetch metadata for a single Gmail message and return an EmailSignal."""
        try:
            msg = self._execute_with_backoff(
                self._service.users().messages().get(
                    userId="me",
                    id=message_id,
                    format="metadata",
                    metadataHeaders=["Subject", "From", "Date", "To", "Cc"],
                )
            )
        except HttpError:
            return None

        headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
        subject = headers.get("Subject", "(no subject)")
        sender = headers.get("From", "")
        snippet = msg.get("snippet", "")
        date_str = headers.get("Date", "")
        date = _parse_date(date_str)
        signal_type = _classify_signal(subject, snippet)

        return EmailSignal(
            message_id=message_id,
            subject=subject,
            sender=sender,
            date=date,
            snippet=snippet,
            signal_type=signal_type,
        )

    def _execute_with_backoff(self, request, max_retries: int = 4):
        """Execute a Google API request with exponential backoff on rate limit errors."""
        delay = 1.0
        for attempt in range(max_retries):
            try:
                return request.execute()
            except HttpError as e:
                if e.resp.status in (429, 500, 503) and attempt < max_retries - 1:
                    time.sleep(delay)
                    delay *= 2
                else:
                    raise


def _parse_date(date_str: str) -> datetime:
    """Parse an RFC 2822 email date string into a UTC datetime."""
    from email.utils import parsedate_to_datetime
    try:
        dt = parsedate_to_datetime(date_str)
        return dt.astimezone(timezone.utc)
    except Exception:
        return datetime.now(tz=timezone.utc)
