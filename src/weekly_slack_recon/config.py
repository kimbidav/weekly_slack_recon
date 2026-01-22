from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import os
from typing import Optional

from dotenv import load_dotenv


@dataclass
class Config:
    slack_bot_token: str
    dk_email: str = "dkimball@candidatelabs.com"
    lookback_days: int = 30
    unclear_followup_days: int = 7
    inactivity_days: int = 5
    include_confused_close: bool = False
    output_markdown_path: Optional[str] = "weekly_slack_reconciliation.md"

    @property
    def lookback_timedelta(self) -> timedelta:
        return timedelta(days=self.lookback_days)

    @property
    def unclear_followup_timedelta(self) -> timedelta:
        return timedelta(days=self.unclear_followup_days)

    @property
    def inactivity_timedelta(self) -> timedelta:
        return timedelta(days=self.inactivity_days)


def load_config() -> Config:
    """Load configuration from environment variables / .env file."""

    load_dotenv()

    slack_bot_token = os.getenv("SLACK_BOT_TOKEN")
    if not slack_bot_token:
        raise RuntimeError(
            "SLACK_BOT_TOKEN must be set in environment or .env file. "
            "This can be either a User OAuth Token (xoxp-...) or Bot Token (xoxb-...)."
        )

    dk_email = os.getenv("DK_EMAIL", "dkimball@candidatelabs.com")

    def _int_env(name: str, default: int) -> int:
        val = os.getenv(name)
        if not val:
            return default
        try:
            return int(val)
        except ValueError:
            return default

    lookback_days = _int_env("LOOKBACK_DAYS", 30)
    unclear_followup_days = _int_env("UNCLEAR_FOLLOWUP_DAYS", 7)
    inactivity_days = _int_env("INACTIVITY_DAYS", 5)

    include_confused_close = os.getenv("INCLUDE_CONFUSED_CLOSE", "false").lower() in {"1", "true", "yes", "y"}

    output_markdown_path = os.getenv("OUTPUT_MARKDOWN_PATH", "weekly_slack_reconciliation.md")

    return Config(
        slack_bot_token=slack_bot_token,
        dk_email=dk_email,
        lookback_days=lookback_days,
        unclear_followup_days=unclear_followup_days,
        inactivity_days=inactivity_days,
        include_confused_close=include_confused_close,
        output_markdown_path=output_markdown_path,
    )
