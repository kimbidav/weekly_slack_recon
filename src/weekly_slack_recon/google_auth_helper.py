"""
Shared Google OAuth2 helper for Gmail and Calendar API clients.
On first use, opens a browser window for authorization; token is cached
to disk so subsequent runs require no interaction.
"""
from __future__ import annotations

import os
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow


def get_credentials(credentials_path: str, token_path: str, scopes: list[str]) -> Credentials:
    """
    Load cached OAuth2 credentials or run the browser-based authorization flow.

    Args:
        credentials_path: Path to the OAuth2 client credentials JSON downloaded
                          from Google Cloud Console.
        token_path:       Path where the authorized token will be cached.
        scopes:           List of OAuth2 scopes to request.

    Returns:
        A valid google.oauth2.credentials.Credentials instance.

    Raises:
        FileNotFoundError: If credentials_path does not exist.
    """
    creds_file = Path(credentials_path)
    if not creds_file.exists():
        raise FileNotFoundError(
            f"Google OAuth credentials not found at: {credentials_path}\n"
            "To set up:\n"
            "  1. Go to https://console.cloud.google.com → APIs & Services → Credentials\n"
            "  2. Create an OAuth 2.0 Client ID (Desktop app type)\n"
            "  3. Download the JSON and save it to the path above\n"
            "  4. Enable Gmail API and Google Calendar API in your project"
        )

    token_file = Path(token_path)
    creds: Credentials | None = None

    # Load cached token if it exists
    if token_file.exists():
        creds = Credentials.from_authorized_user_file(str(token_file), scopes)

    # Refresh expired token or run full auth flow
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(creds_file), scopes)
            creds = flow.run_local_server(port=0)

        # Cache the token for next time
        token_file.parent.mkdir(parents=True, exist_ok=True)
        token_file.write_text(creds.to_json())

    return creds
