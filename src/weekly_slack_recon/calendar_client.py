"""
Google Calendar API client for the Pipeline Status Check workflow.
Searches the primary calendar for interview events matching the pattern
"{candidate first name} x {client name}" within a configurable time window.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from .google_auth_helper import get_credentials

# OAuth scopes needed
SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]


@dataclass
class CalendarEvent:
    """A single calendar event relevant to a candidate interview."""
    event_id: str
    summary: str          # Event title
    start_time: datetime
    end_time: datetime
    is_upcoming: bool     # True if the event is in the future


class CalendarClient:
    """Queries Google Calendar for candidate interview events."""

    def __init__(self, credentials_path: str, token_path: str):
        creds = get_credentials(credentials_path, token_path, SCOPES)
        self._service = build("calendar", "v3", credentials=creds, cache_discovery=False)

    def search_events(
        self,
        candidate_first_name: str,
        client_name: str,
        lookback_days: int = 7,
        lookahead_days: int = 14,
    ) -> list[CalendarEvent]:
        """
        Search for calendar events matching "{candidate_first_name} x {client_name}".

        Searches within the window [now - lookback_days, now + lookahead_days].
        Returns events sorted by start time (most recent first).

        Args:
            candidate_first_name: Candidate's first name (e.g. "Louise").
            client_name:          Client company name (e.g. "Charta").
            lookback_days:        Days in the past to search.
            lookahead_days:       Days in the future to search.

        Returns:
            List of CalendarEvent objects, sorted newest-first.
        """
        now = datetime.now(tz=timezone.utc)
        time_min = (now - timedelta(days=lookback_days)).isoformat()
        time_max = (now + timedelta(days=lookahead_days)).isoformat()

        try:
            result = self._execute_with_backoff(
                self._service.events().list(
                    calendarId="primary",
                    timeMin=time_min,
                    timeMax=time_max,
                    singleEvents=True,
                    orderBy="startTime",
                    maxResults=100,
                    q=candidate_first_name,  # Free-text search on title
                )
            )
        except HttpError as e:
            print(f"[CALENDAR] Search error for '{candidate_first_name}': {e}")
            return []

        events: list[CalendarEvent] = []
        client_lower = client_name.lower()
        first_lower = candidate_first_name.lower()

        for item in result.get("items", []):
            summary = item.get("summary", "")
            summary_lower = summary.lower()

            # Must contain candidate first name
            if first_lower not in summary_lower:
                continue

            # Optionally narrow by client name — check a few common abbreviations
            # e.g. "charta" matches "Charta Health"; "agave" matches "Agave"
            client_words = [w for w in re.split(r"\W+", client_lower) if len(w) > 2]
            if client_words:
                if not any(cw in summary_lower for cw in client_words):
                    continue

            start = _parse_event_dt(item.get("start", {}))
            end = _parse_event_dt(item.get("end", {}))
            is_upcoming = start >= now

            events.append(CalendarEvent(
                event_id=item.get("id", ""),
                summary=summary,
                start_time=start,
                end_time=end,
                is_upcoming=is_upcoming,
            ))

        # Sort: upcoming events first, then past events by recency
        events.sort(key=lambda e: (not e.is_upcoming, e.start_time if e.is_upcoming else -e.start_time.timestamp()))
        return events

    def _execute_with_backoff(self, request, max_retries: int = 4):
        """Execute a Google API request with exponential backoff on quota errors."""
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


def _parse_event_dt(dt_obj: dict) -> datetime:
    """Parse a Google Calendar event dateTime or date into a UTC datetime."""
    dt_str = dt_obj.get("dateTime") or dt_obj.get("date", "")
    if not dt_str:
        return datetime.now(tz=timezone.utc)
    try:
        if "T" in dt_str:
            # Full datetime with timezone
            dt = datetime.fromisoformat(dt_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        else:
            # All-day event — treat as midnight UTC
            from datetime import date
            d = date.fromisoformat(dt_str)
            return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    except Exception:
        return datetime.now(tz=timezone.utc)
