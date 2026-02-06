#!/usr/bin/env python3
"""
Setup Gmail push notifications to Pub/Sub.

Run this once to enable Gmail to send notifications when new emails arrive.
The notification will trigger the Cloud Function.

Prerequisites:
1. Create a Pub/Sub topic in GCP
2. Deploy the Cloud Function with Pub/Sub trigger
3. Run this script to set up the Gmail watch
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

load_dotenv()

# Gmail scopes - read and send (for reply summaries)
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]

CREDENTIALS_DIR = Path(__file__).parent / "data"
TOKEN_PATH = CREDENTIALS_DIR / "gmail_token.json"
CREDENTIALS_PATH = CREDENTIALS_DIR / "gmail_credentials.json"


def get_gmail_service():
    """Authenticate and return Gmail API service."""
    creds = None

    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDENTIALS_PATH.exists():
                print(f"Error: {CREDENTIALS_PATH} not found")
                print("Download OAuth credentials from Google Cloud Console")
                sys.exit(1)

            flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_PATH), SCOPES)
            creds = flow.run_local_server(port=8085)

        CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)
        with open(TOKEN_PATH, "w") as token:
            token.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)


def setup_watch(topic_name: str):
    """
    Set up Gmail push notifications.

    Args:
        topic_name: Full Pub/Sub topic name
                   Format: projects/{project}/topics/{topic}
    """
    service = get_gmail_service()

    # Set up watch request
    # labelIds: Only watch INBOX (you can customize this)
    request = {
        "topicName": topic_name,
        "labelIds": ["INBOX"],
    }

    try:
        response = service.users().watch(userId="me", body=request).execute()
        print("Gmail watch set up successfully!")
        print(f"  History ID: {response.get('historyId')}")
        print(f"  Expiration: {response.get('expiration')}")
        print()
        print("Note: Gmail watch expires after ~7 days.")
        print("You'll need to renew it periodically (or set up a Cloud Scheduler job).")
        return response
    except Exception as e:
        print(f"Error setting up watch: {e}")
        sys.exit(1)


def stop_watch():
    """Stop Gmail push notifications."""
    service = get_gmail_service()

    try:
        service.users().stop(userId="me").execute()
        print("Gmail watch stopped.")
    except Exception as e:
        print(f"Error stopping watch: {e}")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Set up Gmail push notifications")
    parser.add_argument(
        "--topic",
        required=True,
        help="Pub/Sub topic name (projects/{project}/topics/{topic})",
    )
    parser.add_argument(
        "--stop",
        action="store_true",
        help="Stop the watch instead of starting it",
    )

    args = parser.parse_args()

    if args.stop:
        stop_watch()
    else:
        setup_watch(args.topic)


if __name__ == "__main__":
    main()
