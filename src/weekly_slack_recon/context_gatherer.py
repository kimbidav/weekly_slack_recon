"""Context gatherer for LLM enrichment.

Collects all relevant context for a candidate submission from:
1. The submission's own Slack thread (all replies from any user)
2. The parent Slack channel — messages mentioning the candidate by name,
   plus the threads on those messages

Returns a structured context bundle ready to feed to Claude.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

from .config import Config
from .logic import CandidateSubmission
from .slack_client import SlackAPI


@dataclass
class MessageContext:
    """A single message with metadata."""
    author: str  # user ID or display name
    text: str
    timestamp: datetime
    is_thread_reply: bool = False
    source: str = ""  # e.g. "submission_thread", "channel_mention", "mention_thread"


@dataclass
class CandidateContext:
    """All gathered context for one candidate."""
    candidate_name: str
    linkedin_url: str
    channel_name: str
    channel_id: str
    submission_ts: str
    submitted_at: datetime
    current_status: str
    status_reason: Optional[str]
    days_since_submission: int

    # Context messages grouped by source
    thread_messages: List[MessageContext] = field(default_factory=list)
    channel_mentions: List[MessageContext] = field(default_factory=list)
    mention_thread_messages: List[MessageContext] = field(default_factory=list)

    def to_prompt_text(self) -> str:
        """Format all context into a text block for the LLM prompt."""
        lines = []
        lines.append(f"Candidate: {self.candidate_name}")
        lines.append(f"LinkedIn: {self.linkedin_url}")
        lines.append(f"Channel: #{self.channel_name}")
        lines.append(f"Submitted: {self.submitted_at.strftime('%Y-%m-%d')} ({self.days_since_submission} days ago)")
        lines.append(f"Current emoji-based status: {self.current_status}"
                     + (f" ({self.status_reason})" if self.status_reason else ""))
        lines.append("")

        if self.thread_messages:
            lines.append("=== SUBMISSION THREAD ===")
            for msg in sorted(self.thread_messages, key=lambda m: m.timestamp):
                ts_str = msg.timestamp.strftime("%Y-%m-%d %H:%M")
                lines.append(f"[{ts_str}] {msg.author}: {msg.text}")
            lines.append("")

        if self.channel_mentions:
            lines.append("=== CHANNEL MESSAGES MENTIONING THIS CANDIDATE ===")
            for msg in sorted(self.channel_mentions, key=lambda m: m.timestamp):
                ts_str = msg.timestamp.strftime("%Y-%m-%d %H:%M")
                lines.append(f"[{ts_str}] {msg.author}: {msg.text}")
            lines.append("")

        if self.mention_thread_messages:
            lines.append("=== THREADS ON CHANNEL MENTIONS ===")
            for msg in sorted(self.mention_thread_messages, key=lambda m: m.timestamp):
                ts_str = msg.timestamp.strftime("%Y-%m-%d %H:%M")
                prefix = "  (reply) " if msg.is_thread_reply else ""
                lines.append(f"{prefix}[{ts_str}] {msg.author}: {msg.text}")
            lines.append("")

        if not (self.thread_messages or self.channel_mentions or self.mention_thread_messages):
            lines.append("(No additional context found beyond the initial submission)")

        return "\n".join(lines)


# Common English nickname mappings (first name -> set of variants).
# When we see "Andrew" as a first name, we also search for "andy", "drew", etc.
NICKNAME_MAP: Dict[str, List[str]] = {
    "alexander": ["alex", "xander"],
    "alexandra": ["alex", "lexi", "sandra"],
    "andrew": ["andy", "drew"],
    "anthony": ["tony", "ant"],
    "benjamin": ["ben", "benny"],
    "catherine": ["kate", "cathy", "cat"],
    "charles": ["charlie", "chuck"],
    "christopher": ["chris"],
    "daniel": ["dan", "danny"],
    "david": ["dave"],
    "deborah": ["deb", "debbie"],
    "edward": ["ed", "eddie", "ted"],
    "elizabeth": ["liz", "beth", "eliza", "lizzy"],
    "emily": ["em"],
    "eugene": ["gene"],
    "frederick": ["fred", "freddy"],
    "gabriel": ["gabe"],
    "gregory": ["greg"],
    "james": ["jim", "jimmy", "jamie"],
    "jason": ["jay"],
    "jennifer": ["jen", "jenny"],
    "jessica": ["jess", "jessie"],
    "jonathan": ["jon", "john", "jonny"],
    "joseph": ["joe", "joey"],
    "joshua": ["josh"],
    "katherine": ["kate", "kathy", "kat"],
    "lawrence": ["larry"],
    "margaret": ["maggie", "meg", "peggy"],
    "matthew": ["matt"],
    "michael": ["mike", "mikey"],
    "nathaniel": ["nate", "nathan"],
    "nicholas": ["nick", "nicky"],
    "patricia": ["pat", "trish"],
    "patrick": ["pat"],
    "peter": ["pete"],
    "philip": ["phil"],
    "raymond": ["ray"],
    "rebecca": ["becca", "becky"],
    "richard": ["rich", "rick", "dick"],
    "robert": ["rob", "bob", "bobby"],
    "ronald": ["ron", "ronnie"],
    "samuel": ["sam", "sammy"],
    "stephanie": ["steph"],
    "stephen": ["steve"],
    "steven": ["steve"],
    "theodore": ["theo", "ted", "teddy"],
    "thomas": ["tom", "tommy"],
    "timothy": ["tim", "timmy"],
    "victoria": ["vicky", "tori"],
    "william": ["will", "bill", "billy", "liam"],
    "zachary": ["zach", "zack"],
}

# Build reverse map: nickname -> canonical names (for bidirectional matching)
_REVERSE_NICKNAME: Dict[str, List[str]] = {}
for _canonical, _nicks in NICKNAME_MAP.items():
    for _nick in _nicks:
        _REVERSE_NICKNAME.setdefault(_nick, []).append(_canonical)


def _build_name_variants(candidate_name: str) -> List[str]:
    """Build search variants for a candidate name, including common nicknames.

    For "Andrew Liang" we produce: ["andrew liang", "andy liang", "drew liang",
                                     "andrew", "andy", "drew"]
    Last name alone is included only if 5+ chars.
    """
    name = candidate_name.strip()
    if not name:
        return []

    parts = name.lower().split()
    variants: List[str] = [name.lower()]  # full name as-is

    if len(parts) < 2:
        # Single name — just use it if long enough
        if len(parts[0]) >= 4:
            return [parts[0]]
        return variants

    first = parts[0]
    last = parts[-1]

    # Collect all first-name variants (original + nicknames)
    first_variants = {first}

    # Add nicknames for this first name
    if first in NICKNAME_MAP:
        first_variants.update(NICKNAME_MAP[first])

    # Also check reverse: if "andy" is the given name, add "andrew"
    if first in _REVERSE_NICKNAME:
        first_variants.update(_REVERSE_NICKNAME[first])

    # Build "first last" combos for each variant
    for fv in first_variants:
        combo = f"{fv} {last}"
        if combo not in variants:
            variants.append(combo)

    # Add standalone first-name variants (only if 4+ chars to avoid false positives)
    for fv in first_variants:
        if len(fv) >= 4 and fv not in variants:
            variants.append(fv)

    # Add last name if long enough (to catch "Liang got an offer")
    if len(last) >= 5 and last not in variants:
        variants.append(last)

    return variants


def _message_mentions_candidate(text: str, name_variants: List[str]) -> bool:
    """Check if a message text mentions the candidate by any name variant.

    Uses word-boundary matching to reduce false positives.
    """
    if not text:
        return False
    lowered = text.lower()
    for variant in name_variants:
        # For multi-word variants (full name), simple substring is fine
        if " " in variant:
            if variant in lowered:
                return True
        else:
            # Single word: use word boundary check to avoid partial matches
            # e.g. "andrew" shouldn't match "andrewski"
            pattern = r'\b' + re.escape(variant) + r'\b'
            if re.search(pattern, lowered):
                return True
    return False


def _resolve_user_display(
    slack: SlackAPI,
    user_id: Optional[str],
    user_cache: Dict[str, str],
) -> str:
    """Resolve a Slack user ID to a display name, with caching."""
    if not user_id:
        return "unknown"
    if user_id in user_cache:
        return user_cache[user_id]

    try:
        resp = slack.client.users_info(user=user_id)
        user = resp.get("user", {})
        profile = user.get("profile", {})
        display = (
            profile.get("display_name")
            or profile.get("real_name")
            or user.get("name")
            or user_id
        )
        user_cache[user_id] = display
        return display
    except Exception:
        user_cache[user_id] = user_id
        return user_id


def gather_context_for_submission(
    cfg: Config,
    slack: SlackAPI,
    submission: CandidateSubmission,
    user_cache: Optional[Dict[str, str]] = None,
) -> CandidateContext:
    """Gather all available context for a single candidate submission.

    1. Fetches the full submission thread (all replies).
    2. Scans the parent channel for messages mentioning the candidate name
       within the lookback window, and fetches their threads too.
    """
    if user_cache is None:
        user_cache = {}

    ctx = CandidateContext(
        candidate_name=submission.candidate_name,
        linkedin_url=submission.linkedin_url,
        channel_name=submission.channel_name,
        channel_id=submission.channel_id,
        submission_ts=f"{submission.submitted_at.timestamp():.6f}",
        submitted_at=submission.submitted_at,
        current_status=submission.status,
        status_reason=submission.status_reason,
        days_since_submission=submission.days_since_submission,
    )

    # --- 1. Submission thread ---
    try:
        thread_msgs = slack.get_thread_messages(
            submission.channel_id,
            ctx.submission_ts,
        )
        for msg in thread_msgs:
            msg_time = SlackAPI.parse_ts(msg.ts)
            author = _resolve_user_display(slack, msg.user, user_cache)
            ctx.thread_messages.append(
                MessageContext(
                    author=author,
                    text=msg.text or "",
                    timestamp=msg_time,
                    is_thread_reply=(msg.ts != ctx.submission_ts),
                    source="submission_thread",
                )
            )
    except Exception as e:
        print(f"[ENRICH] Warning: could not fetch submission thread for "
              f"{submission.candidate_name}: {e}")

    # --- 2. Channel messages mentioning candidate ---
    name_variants = _build_name_variants(submission.candidate_name)
    if not name_variants:
        return ctx

    now = datetime.now(tz=timezone.utc)
    oldest_ts = (now - cfg.lookback_timedelta).timestamp()

    # Track which thread_ts values we've already fetched (submission thread)
    seen_threads = {ctx.submission_ts}

    try:
        for msg in slack.iter_channel_messages_since(submission.channel_id, oldest_ts):
            # Skip the original submission message itself
            if msg.ts == ctx.submission_ts:
                continue

            # Only top-level messages (not thread replies appearing in channel)
            if msg.thread_ts and msg.thread_ts != msg.ts:
                continue

            if not _message_mentions_candidate(msg.text, name_variants):
                continue

            msg_time = SlackAPI.parse_ts(msg.ts)
            author = _resolve_user_display(slack, msg.user, user_cache)

            ctx.channel_mentions.append(
                MessageContext(
                    author=author,
                    text=msg.text or "",
                    timestamp=msg_time,
                    is_thread_reply=False,
                    source="channel_mention",
                )
            )

            # Fetch thread on this mention if it has replies
            thread_ts = msg.thread_ts or msg.ts
            if thread_ts not in seen_threads:
                seen_threads.add(thread_ts)
                try:
                    mention_thread = slack.get_thread_messages(
                        submission.channel_id, thread_ts
                    )
                    for t_msg in mention_thread:
                        # Skip the parent (already in channel_mentions)
                        if t_msg.ts == msg.ts:
                            continue
                        t_time = SlackAPI.parse_ts(t_msg.ts)
                        t_author = _resolve_user_display(
                            slack, t_msg.user, user_cache
                        )
                        ctx.mention_thread_messages.append(
                            MessageContext(
                                author=t_author,
                                text=t_msg.text or "",
                                timestamp=t_time,
                                is_thread_reply=True,
                                source="mention_thread",
                            )
                        )
                except Exception as e:
                    print(f"[ENRICH] Warning: could not fetch mention thread "
                          f"for {submission.candidate_name}: {e}")

    except Exception as e:
        print(f"[ENRICH] Warning: could not scan channel mentions for "
              f"{submission.candidate_name}: {e}")

    return ctx


def gather_context_batch(
    cfg: Config,
    slack: SlackAPI,
    submissions: List[CandidateSubmission],
    progress_callback=None,
) -> List[CandidateContext]:
    """Gather context for a batch of submissions.

    Args:
        cfg: Configuration
        slack: Slack API client
        submissions: List of submissions to enrich
        progress_callback: Optional callable(current, total, candidate_name)
    """
    user_cache: Dict[str, str] = {}
    contexts: List[CandidateContext] = []

    for i, sub in enumerate(submissions):
        if progress_callback:
            progress_callback(i, len(submissions), sub.candidate_name)

        ctx = gather_context_for_submission(cfg, slack, sub, user_cache)
        contexts.append(ctx)

    if progress_callback:
        progress_callback(len(submissions), len(submissions), "done")

    return contexts
