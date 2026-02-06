"""Gmail API client for fetching Amazon order emails (read-only)."""

import base64
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# Gmail scopes - read and send (for reply summaries)
SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.send',
]

# Paths for OAuth credentials
CREDENTIALS_DIR = Path(__file__).parent / "data"
TOKEN_PATH = CREDENTIALS_DIR / "gmail_token.json"
CREDENTIALS_PATH = CREDENTIALS_DIR / "gmail_credentials.json"


@dataclass
class RawEmail:
    """Raw email data from Gmail API."""
    uid: str
    message_id: str
    subject: str
    from_addr: str
    date: datetime
    html_body: str
    text_body: str


class GmailFetcher:
    """Fetch emails from Gmail via API (read-only)."""

    # Amazon sender addresses to search for
    AMAZON_SENDERS = [
        "auto-confirm@amazon.com",
        "ship-confirm@amazon.com",
        "shipment-tracking@amazon.com",
        "order-update@amazon.com",
        "no-reply@amazon.com",
    ]

    def __init__(self):
        """Initialize Gmail API client."""
        self.service = None
        self.creds = None

    def _get_credentials(self) -> Credentials:
        """Get or refresh OAuth credentials."""
        creds = None

        # Load existing token if available
        if TOKEN_PATH.exists():
            creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

        # If no valid credentials, run OAuth flow
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not CREDENTIALS_PATH.exists():
                    raise FileNotFoundError(
                        f"Gmail credentials not found at {CREDENTIALS_PATH}\n"
                        "Please download OAuth credentials from Google Cloud Console.\n"
                        "See README for setup instructions."
                    )

                flow = InstalledAppFlow.from_client_secrets_file(
                    str(CREDENTIALS_PATH), SCOPES
                )
                creds = flow.run_local_server(port=0)

            # Save the credentials for future runs
            CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)
            with open(TOKEN_PATH, 'w') as token:
                token.write(creds.to_json())

        return creds

    def connect(self) -> None:
        """Connect to Gmail API."""
        self.creds = self._get_credentials()
        self.service = build('gmail', 'v1', credentials=self.creds)

    def disconnect(self) -> None:
        """Disconnect (cleanup)."""
        self.service = None
        self.creds = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()

    def _parse_email_date(self, headers: List[dict]) -> datetime:
        """Parse date from email headers."""
        for header in headers:
            if header['name'].lower() == 'date':
                date_str = header['value']
                # Try common date formats
                for fmt in [
                    '%a, %d %b %Y %H:%M:%S %z',
                    '%a, %d %b %Y %H:%M:%S %Z',
                    '%d %b %Y %H:%M:%S %z',
                ]:
                    try:
                        return datetime.strptime(date_str[:31], fmt)
                    except ValueError:
                        continue
                # Fallback: try to parse just the date part
                try:
                    # Remove timezone info and parse
                    clean_date = ' '.join(date_str.split()[:5])
                    return datetime.strptime(clean_date, '%a, %d %b %Y %H:%M:%S')
                except ValueError:
                    pass
        return datetime.now()

    def _get_header(self, headers: List[dict], name: str) -> str:
        """Get a specific header value."""
        for header in headers:
            if header['name'].lower() == name.lower():
                return header['value']
        return ""

    def _get_body(self, payload: dict) -> tuple[str, str]:
        """Extract HTML and text body from email payload."""
        html_body = ""
        text_body = ""

        def extract_parts(part: dict):
            nonlocal html_body, text_body

            mime_type = part.get('mimeType', '')
            body = part.get('body', {})
            data = body.get('data', '')

            if data:
                decoded = base64.urlsafe_b64decode(data).decode('utf-8', errors='replace')
                if mime_type == 'text/html':
                    html_body = decoded
                elif mime_type == 'text/plain':
                    text_body = decoded

            # Recursively process parts
            for sub_part in part.get('parts', []):
                extract_parts(sub_part)

        extract_parts(payload)
        return html_body, text_body

    def fetch_amazon_emails(
        self,
        since_date: Optional[datetime] = None,
        limit: int = 50
    ) -> List[RawEmail]:
        """
        Fetch Amazon order confirmation emails.

        Args:
            since_date: Only fetch emails after this date
            limit: Maximum number of emails to fetch

        Returns:
            List of RawEmail objects
        """
        if not self.service:
            raise RuntimeError("Not connected. Use 'with' statement or call connect()")

        # Build search query
        query_parts = []

        # Search for Amazon senders
        sender_query = " OR ".join([f"from:{s}" for s in self.AMAZON_SENDERS])
        query_parts.append(f"({sender_query})")

        # Date filter
        if since_date:
            date_str = since_date.strftime("%Y/%m/%d")
            query_parts.append(f"after:{date_str}")

        # Subject filter for order-related emails
        query_parts.append("(subject:order OR subject:shipped OR subject:delivered)")

        query = " ".join(query_parts)

        # Fetch message IDs
        results = self.service.users().messages().list(
            userId='me',
            q=query,
            maxResults=limit
        ).execute()

        messages = results.get('messages', [])

        if not messages:
            return []

        emails = []
        for msg_info in messages:
            try:
                # Fetch full message
                msg = self.service.users().messages().get(
                    userId='me',
                    id=msg_info['id'],
                    format='full'
                ).execute()

                payload = msg.get('payload', {})
                headers = payload.get('headers', [])

                subject = self._get_header(headers, 'Subject')
                from_addr = self._get_header(headers, 'From')
                message_id = self._get_header(headers, 'Message-ID')
                date = self._parse_email_date(headers)

                html_body, text_body = self._get_body(payload)

                # Filter to order confirmations
                subject_lower = subject.lower()
                if not any(kw in subject_lower for kw in ['order', 'shipped', 'delivered', 'your amazon']):
                    continue

                emails.append(RawEmail(
                    uid=msg_info['id'],
                    message_id=message_id,
                    subject=subject,
                    from_addr=from_addr,
                    date=date,
                    html_body=html_body,
                    text_body=text_body
                ))

            except Exception as e:
                print(f"Error fetching email {msg_info['id']}: {e}")
                continue

        return emails
