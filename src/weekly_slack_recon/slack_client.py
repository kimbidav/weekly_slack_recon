from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional
import time

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError


@dataclass
class SlackMessage:
    channel: str
    ts: str
    user: Optional[str]
    text: str
    thread_ts: Optional[str]
    reactions: List[Dict]


class SlackAPI:
    """Thin wrapper over Slack WebClient for the read-only operations we need."""

    def __init__(self, token: str) -> None:
        self.client = WebClient(token=token)

    def get_user_id_by_email(self, email: str) -> str:
        """Get user ID by email. Tries users.lookupByEmail first, falls back to users.list if scope missing."""
        # Try direct lookup first (requires users:read.email)
        try:
            resp = self.client.users_lookupByEmail(email=email)
            user = resp.get("user")
            if user and "id" in user:
                return user["id"]
        except SlackApiError as e:
            error_code = e.response.get("error", "")
            if error_code == "invalid_auth":
                raise RuntimeError(
                    f"Invalid or expired Slack token. Please check your token at https://api.slack.com/apps "
                    f"and regenerate if needed. Error: {error_code}"
                ) from e
            if error_code == "missing_scope":
                # Fallback: use users.list (requires only users:read)
                try:
                    cursor: Optional[str] = None
                    while True:
                        resp = self.client.users_list(limit=200, cursor=cursor)
                        for user in resp.get("members", []):
                            profile = user.get("profile", {})
                            if profile.get("email") == email:
                                return user["id"]
                        cursor = resp.get("response_metadata", {}).get("next_cursor")
                        if not cursor:
                            break
                    raise RuntimeError(f"No Slack user found for email {email}")
                except SlackApiError as e2:
                    raise RuntimeError(
                        f"Failed to look up user by email {email}. "
                        f"Need either 'users:read.email' scope (for direct lookup) or 'users:read' scope (for list fallback). "
                        f"Error: {e2.response.get('error', 'unknown')}"
                    ) from e2
            else:
                raise RuntimeError(f"Failed to look up user by email {email}: {error_code}") from e

        raise RuntimeError(f"No Slack user found for email {email}")

    def list_candidate_channels_for_user(self, user_id: str) -> List[Dict]:
        """Return public/private channels whose name starts with 'candidatelabs-' and where user is a member."""

        channels: List[Dict] = []
        cursor: Optional[str] = None

        while True:
            try:
                resp = self.client.conversations_list(
                    types="public_channel,private_channel",
                    limit=1000,
                    cursor=cursor,
                )
            except SlackApiError as e:
                raise RuntimeError(f"Failed to list channels: {e.response['error']}") from e

            for ch in resp.get("channels", []):
                name = ch.get("name", "")
                if not name.startswith("candidatelabs-"):
                    continue

                # conversations_list may or may not include is_member depending on auth; fallback to membership check
                if ch.get("is_member"):
                    channels.append(ch)
                else:
                    if self._is_user_in_channel(ch["id"], user_id):
                        channels.append(ch)

            cursor = resp.get("response_metadata", {}).get("next_cursor") or None
            if not cursor:
                break

        return channels

    def _is_user_in_channel(self, channel_id: str, user_id: str) -> bool:
        try:
            resp = self.client.conversations_members(channel=channel_id, limit=1000)
        except SlackApiError:
            # If we can't read members, assume not a member.
            return False

        members = resp.get("members", [])
        return user_id in members

    def iter_channel_messages_since(self, channel_id: str, oldest_ts: float) -> Iterable[SlackMessage]:
        """Yield messages in a channel since a given Unix timestamp (inclusive)."""

        cursor: Optional[str] = None
        while True:
            try:
                resp = self.client.conversations_history(
                    channel=channel_id,
                    oldest=str(oldest_ts),
                    limit=200,
                    cursor=cursor,
                    inclusive=True,
                )
            except SlackApiError as e:
                raise RuntimeError(f"Failed to fetch history for channel {channel_id}: {e.response['error']}") from e

            for m in resp.get("messages", []):
                yield SlackMessage(
                    channel=channel_id,
                    ts=m["ts"],
                    user=m.get("user"),
                    text=m.get("text", ""),
                    thread_ts=m.get("thread_ts"),
                    reactions=m.get("reactions", []),
                )

            if not resp.get("has_more"):
                break

            cursor = resp.get("response_metadata", {}).get("next_cursor") or None
            if not cursor:
                break

    def get_thread_messages(self, channel_id: str, thread_ts: str, max_retries: int = 3) -> List[SlackMessage]:
        """Return all messages in a thread (including the parent).
        
        Handles rate limits with exponential backoff retries.
        Returns empty list if all retries fail (caller should continue processing).
        """
        
        for attempt in range(max_retries):
            try:
                resp = self.client.conversations_replies(channel=channel_id, ts=thread_ts, limit=200)
                
                messages: List[SlackMessage] = []
                for m in resp.get("messages", []):
                    messages.append(
                        SlackMessage(
                            channel=channel_id,
                            ts=m["ts"],
                            user=m.get("user"),
                            text=m.get("text", ""),
                            thread_ts=m.get("thread_ts"),
                            reactions=m.get("reactions", []),
                        )
                    )
                
                return messages
                
            except SlackApiError as e:
                error_code = e.response.get("error", "")
                
                # Handle rate limiting
                if error_code == "ratelimited":
                    retry_after = int(e.response.get("headers", {}).get("Retry-After", "60"))
                    wait_time = retry_after + (attempt * 2)  # Add extra backoff for subsequent retries
                    
                    if attempt < max_retries - 1:
                        print(f"[RATE LIMIT] Waiting {wait_time} seconds before retry {attempt + 2}/{max_retries}...")
                        time.sleep(wait_time)
                        continue
                    else:
                        # All retries exhausted
                        print(f"[WARNING] Rate limited for channel {channel_id} thread {thread_ts} after {max_retries} attempts. Continuing without thread data.")
                        return []
                
                # For other errors, log and return empty list
                if attempt == max_retries - 1:
                    print(f"[WARNING] Failed to fetch thread replies for channel {channel_id} ts {thread_ts}: {error_code}. Continuing without thread data.")
                    return []
                else:
                    # Wait a bit before retrying non-rate-limit errors
                    time.sleep(1 * (attempt + 1))
                    continue
        
        return []

    @staticmethod
    def parse_ts(ts: str) -> datetime:
        # Slack timestamps are like "1701985150.000200" (seconds.micros)
        seconds = float(ts)
        return datetime.fromtimestamp(seconds, tz=timezone.utc)

