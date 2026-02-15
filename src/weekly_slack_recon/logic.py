from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Any, Dict, List, Optional, Tuple

from .slack_client import SlackMessage, SlackAPI
from .status_rules import (
    CLOSED_EMOJIS_BASE,
    CONFUSED_EMOJI,
    IN_PROCESS_EMOJIS,
    CLOSED_KEYWORDS_HARD,
    CLOSED_KEYWORDS_SOFT,
    IN_PROCESS_KEYWORDS,
    StatusCategory,
    text_contains_any,
)
from .config import Config


# Match LinkedIn URLs - handles both linkedin.com and www.linkedin.com
# Also handles Slack link format: <https://linkedin.com/in/...|Candidate Name> or <https://linkedin.com/in/...>
# Also handles URLs with query params and fragments (we'll strip those later)
LINKEDIN_REGEX = re.compile(
    r"(?:<)?https?://(?:[a-zA-Z0-9-]+\.)?linkedin\.com/[^\s>|]+(?:[|>])?", re.IGNORECASE
)


@dataclass
class CandidateSubmission:
    candidate_name: str
    linkedin_url: str
    channel_name: str
    channel_id: str
    submitted_at: datetime
    status: str
    status_reason: Optional[str]
    days_since_submission: int
    needs_followup: bool
    slack_url: Optional[str] = None


def extract_linkedin_urls(text: str) -> List[str]:
    """Extract LinkedIn URLs from text, handling Slack link formatting."""
    if not text:
        return []
    
    urls = LINKEDIN_REGEX.findall(text)
    # Clean up Slack link format: remove < and > and anything after |
    cleaned = []
    for url in urls:
        # Remove leading < if present
        if url.startswith("<"):
            url = url[1:]
        # Remove trailing > or |...> if present
        if "|" in url:
            url = url.split("|")[0]
        if url.endswith(">"):
            url = url[:-1]
        cleaned.append(url)
    return cleaned


def canonicalize_linkedin(url: str) -> str:
    url = url.strip()
    # Strip tracking params, anchors, etc.
    if "?" in url:
        url = url.split("?", 1)[0]
    if "#" in url:
        url = url.split("#", 1)[0]
    # Normalize trailing slash
    if url.endswith("/"):
        url = url[:-1]
    return url


def infer_candidate_name(text: str, linkedin_url: str) -> str:
    """Best-effort extraction of candidate name from text.

    Handles Slack link format: <https://linkedin.com/in/...|Candidate Name>
    Falls back to text before URL, then LinkedIn path segment.
    """

    if not text:
        # Fallback: use the last path segment of the LinkedIn URL
        path = linkedin_url.rstrip("/").split("/")[-1]
        return path.replace("-", " ") or linkedin_url

    # First, check if the URL is in Slack link format: <url|name>
    slack_link_pattern = re.compile(
        rf"<https?://(?:[a-zA-Z0-9-]+\.)?linkedin\.com/[^|>]+\|([^>]+)>", re.IGNORECASE
    )
    match = slack_link_pattern.search(text)
    if match:
        name = match.group(1).strip()
        if name:
            return name

    # Try to find the URL in the text and look for name before it
    idx = text.find(linkedin_url)
    if idx == -1:
        # URL might be in Slack format, try finding it
        idx = text.find("linkedin.com")
        if idx == -1:
            # Fallback: use the last path segment of the LinkedIn URL
            path = linkedin_url.rstrip("/").split("/")[-1]
            return path.replace("-", " ") or linkedin_url

    prefix = text[:idx].strip()
    words = prefix.split()
    if words:
        # Use last 2–4 words as a possible name
        for size in range(4, 1, -1):
            if len(words) >= size:
                candidate = " ".join(words[-size:])
                # crude filter: must have at least one space and letters
                if any(c.isalpha() for c in candidate) and "@" not in candidate:
                    return candidate.strip(",. ")

    # Fallback: use the last path segment of the LinkedIn URL
    path = linkedin_url.rstrip("/").split("/")[-1]
    return path.replace("-", " ") or linkedin_url


def _classify_from_emojis(reactions: List[Dict], include_confused_close: bool) -> Optional[Tuple[str, str]]:
    """Classify signals from reactions (thread-level / non-authoritative).

    Only returns IN_PROCESS_EXPLICIT for white_check_mark (✅). CLOSED is only determined by
    no_entry/no_entry_sign emoji on the parent message (authoritative).

    1. ⛔ on parent (declined) – terminal CLOSED (handled separately)
    2. ✅ (white_check_mark) – IN PROCESS — explicit (only emoji that marks explicit)
    3. Keyword signals in thread replies
    4. Silence
    """

    for reaction in reactions:
        name = reaction.get("name")
        if not name:
            continue
        # Only white_check_mark marks as explicit
        if name == "white_check_mark":
            return StatusCategory.IN_PROCESS_EXPLICIT, f":{name}:"
        # Note: CLOSED is only determined by no_entry/no_entry_sign on parent message
    return None


def _classify_from_text(text: str) -> Optional[Tuple[str, str]]:
    # Note: CLOSED is only determined by no_entry/no_entry_sign emoji on parent message
    # IN_PROCESS_EXPLICIT is only determined by white_check_mark emoji
    # Text keywords no longer mark as explicit (only green checkmark does)
    return None


def _manual_status_from_parent_reactions(
    cfg: Config, reactions: List[Dict]
) -> Tuple[Optional[str], Optional[str], bool]:
    """Return (status, reason, is_hard_decline) from authoritative parent reactions.

    Only emoji reactions on the *parent submission message* are treated as
    authoritative manual annotations.

    CLOSED is ONLY determined by no_entry/no_entry_sign (⛔) emoji.
    Other reactions (including other "close" emojis) do not mark as CLOSED.

    When multiple reactions exist, precedence order determines the result:
    1. ⛔ (no_entry/no_entry_sign) → terminal CLOSED (overrides everything)
    2. In-process reactions → IN PROCESS — explicit
    """

    names = [r.get("name") for r in reactions or [] if r.get("name")]

    # 1) ⛔ on parent – terminal CLOSED (no_entry / no_entry_sign)
    # This is the ONLY way to mark as CLOSED
    for name in names:
        if name in {"no_entry", "no_entry_sign"}:
            return StatusCategory.CLOSED, f":{name}:", True

    # 2) Only white_check_mark (✅) on parent marks as IN PROCESS — explicit
    for name in names:
        if name == "white_check_mark":
            return StatusCategory.IN_PROCESS_EXPLICIT, f":{name}:", False

    return None, None, False


def infer_status_for_submission(
    cfg: Config,
    submission_msg: SlackMessage,
    thread_messages: List[SlackMessage],
    now: datetime,
) -> Tuple[str, Optional[str], datetime, bool]:
    """Apply precedence rules across manual annotations, emojis, and text over time.

    Returns (status, status_reason, last_activity_time, has_no_parent_reactions).
    has_no_parent_reactions is True if there are no reactions on the parent message.
    """

    submission_time = SlackAPI.parse_ts(submission_msg.ts)
    last_activity_time = submission_time

    parent_reactions = submission_msg.reactions or []
    has_no_parent_reactions = len(parent_reactions) == 0

    # First, check for authoritative manual annotations on the parent message.
    manual_status, manual_reason, is_hard_decline = _manual_status_from_parent_reactions(
        cfg, parent_reactions
    )

    if manual_status == StatusCategory.CLOSED and is_hard_decline:
        # ⛔ on parent – must be CLOSED regardless of anything else.
        return StatusCategory.CLOSED, manual_reason, last_activity_time, has_no_parent_reactions

    # Collect chronological events after submission (including parent for
    # non-authoritative inference where manual override is not present).
    events: List[Tuple[datetime, List[Dict], str]] = []

    # Include the submission message itself (for reactions and keywords)
    events.append(
        (
            submission_time,
            parent_reactions,
            submission_msg.text or "",
        )
    )

    for msg in thread_messages:
        msg_time = SlackAPI.parse_ts(msg.ts)
        if msg_time <= submission_time:
            continue
        last_activity_time = max(last_activity_time, msg_time)
        events.append((msg_time, msg.reactions or [], msg.text or ""))

    # Sort by time ascending
    events.sort(key=lambda x: x[0])

    # Default: IN PROCESS — unclear (no explicit close or progress signal).
    status = StatusCategory.IN_PROCESS_UNCLEAR
    status_reason: Optional[str] = None

    # Seed with any non-terminal manual status from parent before processing
    # thread-level reactions/keywords.
    if manual_status and not is_hard_decline:
        status = manual_status
        status_reason = manual_reason

    for event_time, reactions, text in events:
        # We have already processed manual overrides from the parent (no_entry and white_check_mark only).
        # From here, we only process explicit signals from thread reactions.
        # CLOSED can only come from no_entry/no_entry_sign on parent message.
        # IN_PROCESS_EXPLICIT can only come from white_check_mark (parent or thread).
        emoji_result = _classify_from_emojis(reactions, cfg.include_confused_close)

        # Only process explicit signals (not CLOSED - that's only from parent no_entry)
        if status != StatusCategory.CLOSED:
            # Only white_check_mark marks as explicit
            if emoji_result and emoji_result[0] == StatusCategory.IN_PROCESS_EXPLICIT:
                status, status_reason = emoji_result

    return status, status_reason, last_activity_time, has_no_parent_reactions


def build_candidate_submissions(
    cfg: Config,
    slack: SlackAPI,
    dk_user_id: str,
    channels: List[Dict],
    now: Optional[datetime] = None,
) -> Tuple[List[CandidateSubmission], Dict[str, Any]]:
    """Scan channels to build the submission ledger with inferred statuses."""

    if now is None:
        now = datetime.now(tz=timezone.utc)

    oldest_ts = (now - cfg.lookback_timedelta).timestamp()

    # Fetch workspace domain once for building Slack permalink URLs
    workspace_domain = slack.get_workspace_domain()

    channel_id_to_name: Dict[str, str] = {c["id"]: c.get("name", c["id"]) for c in channels}

    submissions: List[CandidateSubmission] = []
    
    # Debug counters
    total_messages = 0
    top_level_messages = 0
    dk_messages = 0
    messages_with_linkedin = 0
    sample_dk_messages = []  # Store a few examples for debugging

    for ch in channels:
        channel_id = ch["id"]
        channel_name = ch.get("name", channel_id)

        for msg in slack.iter_channel_messages_since(channel_id, oldest_ts):
            total_messages += 1
            
            # Only top-level messages (no thread_ts or thread_ts == ts)
            if msg.thread_ts and msg.thread_ts != msg.ts:
                continue
            top_level_messages += 1

            if msg.user != dk_user_id:
                continue
            dk_messages += 1
            
            # Collect sample messages for debugging
            if len(sample_dk_messages) < 3 and msg.text:
                sample_dk_messages.append((channel_name, msg.text[:100]))

            urls = extract_linkedin_urls(msg.text)
            if not urls:
                continue
            messages_with_linkedin += 1

            # For now, treat each URL as a separate candidate (in practice usually 1).
            thread_ts = msg.thread_ts or msg.ts
            try:
                thread_messages = slack.get_thread_messages(channel_id, thread_ts)
            except Exception as e:
                # If thread fetch fails, continue with empty thread (will use parent message only)
                print(f"[WARNING] Could not fetch thread for {channel_name}: {e}")
                thread_messages = []

            for raw_url in urls:
                linkedin_url = canonicalize_linkedin(raw_url)
                candidate_name = infer_candidate_name(msg.text, raw_url)

                status, status_reason, last_activity_time, has_no_parent_reactions = infer_status_for_submission(
                    cfg, msg, thread_messages, now
                )

                days_since_submission = (now - SlackAPI.parse_ts(msg.ts)).days
                inactivity_days = (now - last_activity_time).days

                # Needs follow-up if:
                # 1. No reactions on parent message (regardless of days), OR
                # 2. Status is IN PROCESS — unclear and meets the day thresholds
                needs_followup = has_no_parent_reactions or (
                    status == StatusCategory.IN_PROCESS_UNCLEAR
                    and days_since_submission >= cfg.unclear_followup_days
                    and inactivity_days >= cfg.inactivity_days
                )

                # Build Slack permalink that opens the thread directly:
                # Adding thread_ts and cid params makes Slack open the thread panel
                # so cmd-click opens each thread in its own window.
                msg_ts_no_dot = msg.ts.replace('.', '')
                slack_url = (
                    f"https://{workspace_domain}/archives/{channel_id}/p{msg_ts_no_dot}"
                    f"?thread_ts={msg.ts}&cid={channel_id}"
                )

                submissions.append(
                    CandidateSubmission(
                        candidate_name=candidate_name,
                        linkedin_url=linkedin_url,
                        channel_name=channel_name,
                        channel_id=channel_id,
                        submitted_at=SlackAPI.parse_ts(msg.ts),
                        status=status,
                        status_reason=status_reason,
                        days_since_submission=days_since_submission,
                        needs_followup=needs_followup,
                        slack_url=slack_url,
                    )
                )

    return submissions, {
        "total_messages": total_messages,
        "top_level_messages": top_level_messages,
        "dk_messages": dk_messages,
        "messages_with_linkedin": messages_with_linkedin,
        "sample_dk_messages": sample_dk_messages,
    }
