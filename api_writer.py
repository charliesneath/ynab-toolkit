"""External API write operations (Anthropic Batch API, Firestore, Gmail).

This module contains all external API operations that modify remote state.
For read-only operations, use the service clients directly.

IMPORTANT: Importing from this module indicates destructive intent and
will trigger permission prompts via the auto_approve_reads hook.
"""

import os
from datetime import datetime
from pathlib import Path
from typing import Optional


# =============================================================================
# Firestore Write Operations
# =============================================================================

def save_history_id(history_id: str, project_id: Optional[str] = None) -> None:
    """Save the last processed Gmail history ID to Firestore.

    Args:
        history_id: The Gmail history ID to save
        project_id: GCP project ID (defaults to GCP_PROJECT_ID env var)
    """
    try:
        from google.cloud import firestore
        if project_id is None:
            project_id = os.getenv("GCP_PROJECT_ID")
        db = firestore.Client(project=project_id)
        db.collection("config").document("gmail_history").set({
            "history_id": history_id,
            "updated_at": datetime.now().isoformat()
        })
        print(f"Saved history ID: {history_id}")
    except Exception as e:
        print(f"Error saving history ID: {e}")


def mark_email_processed(email_id: str, order_id: str, project_id: Optional[str] = None) -> bool:
    """Mark an email as processed in Firestore.

    Uses atomic create() to prevent race conditions - returns False if
    another instance already processed this email.

    Args:
        email_id: The Gmail message ID
        order_id: The Amazon order ID from the email
        project_id: GCP project ID (defaults to GCP_PROJECT_ID env var)

    Returns:
        True if marked successfully, False if already processed
    """
    try:
        from google.cloud import firestore
        if project_id is None:
            project_id = os.getenv("GCP_PROJECT_ID")
        db = firestore.Client(project=project_id)
        doc_ref = db.collection("processed_emails").document(email_id)

        # Use create() which fails if document exists - atomic operation
        doc_ref.create({
            "order_id": order_id,
            "processed_at": datetime.now().isoformat()
        })
        return True
    except Exception as e:
        # Document already exists = another instance processed it
        if "already exists" in str(e).lower():
            print(f"Email {email_id} already processed by another instance")
            return False
        print(f"Error marking email processed: {e}")
        return False


def save_watch_expiration(expiration: int, project_id: Optional[str] = None) -> None:
    """Save the Gmail watch expiration timestamp to Firestore.

    Args:
        expiration: Unix timestamp (milliseconds) when watch expires
        project_id: GCP project ID (defaults to GCP_PROJECT_ID env var)
    """
    try:
        from google.cloud import firestore
        if project_id is None:
            project_id = os.getenv("GCP_PROJECT_ID")
        db = firestore.Client(project=project_id)
        db.collection("config").document("gmail_watch").set({
            "expiration": expiration,
            "updated_at": datetime.now().isoformat()
        })
        print(f"Saved watch expiration: {expiration}")
    except Exception as e:
        print(f"Error saving watch expiration: {e}")


# =============================================================================
# Anthropic Batch API Write Operations
# =============================================================================

def submit_batch_categorization(
    requests: list,
    client,
    cache_dir: Path,
    cache_file: Path,
    items_map: dict,
    ynab_categories: list,
    cat_to_group: dict,
) -> str:
    """Submit categorization requests to Anthropic Batches API.

    This submits items for async categorization (50% cheaper, up to 24 hours).

    Args:
        requests: List of batch request dicts with custom_id and params
        client: Anthropic client
        cache_dir: Directory for batch tracking
        cache_file: The cache file these results will be applied to
        items_map: Mapping of import_id to items list
        ynab_categories: List of valid YNAB category names
        cat_to_group: Mapping of category name to group name

    Returns:
        Batch ID for tracking, or empty string on failure
    """
    from file_writer import save_pending_batches

    # Import here to avoid circular dependency
    def load_pending_batches(cache_dir: Path) -> dict:
        batch_file = cache_dir / "pending_batches.json"
        if batch_file.exists():
            try:
                import json
                with open(batch_file, "r") as f:
                    return json.load(f)
            except Exception:
                pass
        return {"batches": []}

    print(f"Submitting {len(requests)} categorization requests to Batches API...")
    print("  (50% cheaper than synchronous API, results in up to 24 hours)")

    try:
        batch = client.messages.batches.create(requests=requests)
        batch_id = batch.id

        print(f"\nBatch submitted successfully!")
        print(f"  Batch ID: {batch_id}")
        print(f"  Status: {batch.processing_status}")
        print(f"  Requests: {len(requests)}")

        # Save batch info for tracking
        pending = load_pending_batches(cache_dir)
        pending["batches"].append({
            "batch_id": batch_id,
            "cache_file": str(cache_file),
            "submitted_at": datetime.now().isoformat(),
            "request_count": len(requests),
            "items": items_map,
            "ynab_categories": ynab_categories,
            "cat_to_group": cat_to_group,
        })
        save_pending_batches(cache_dir, pending)

        print(f"\nTo check status: python process_transactions.py --batch-status {batch_id}")
        print(f"To get results:  python process_transactions.py --batch-results {batch_id}")

        return batch_id

    except Exception as e:
        print(f"Error submitting batch: {e}")
        return ""


def cancel_batch(batch_id: str, client) -> bool:
    """Cancel a pending batch job.

    Args:
        batch_id: The batch ID to cancel
        client: Anthropic client

    Returns:
        True if cancelled successfully
    """
    try:
        client.messages.batches.cancel(batch_id)
        return True
    except Exception as e:
        print(f"Error cancelling batch: {e}")
        return False


# =============================================================================
# Gmail Write Operations
# =============================================================================

def setup_gmail_watch(gmail_service, project_id: str, topic_name: str) -> dict:
    """Set up Gmail push notifications.

    Args:
        gmail_service: Authenticated Gmail API service
        project_id: GCP project ID
        topic_name: Pub/Sub topic name

    Returns:
        Watch response with historyId and expiration
    """
    request = {
        "topicName": f"projects/{project_id}/topics/{topic_name}",
        "labelIds": ["INBOX"],
    }
    response = gmail_service.users().watch(userId="me", body=request).execute()
    return response


def stop_gmail_watch(gmail_service) -> bool:
    """Stop Gmail push notifications.

    Args:
        gmail_service: Authenticated Gmail API service

    Returns:
        True if stopped successfully
    """
    try:
        gmail_service.users().stop(userId="me").execute()
        return True
    except Exception as e:
        print(f"Error stopping Gmail watch: {e}")
        return False
