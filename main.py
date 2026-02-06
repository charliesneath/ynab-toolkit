"""Cloud Function entry point for processing Amazon receipt emails."""

import base64
import json
import os
import re
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional

import anthropic
import functions_framework
from cloudevents.http import CloudEvent
from google.cloud import secretmanager
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from amazon_parser import AmazonOrder, AmazonItem
from categorizer import categorize_order, categorize_simple, CategorizationResult
from email_parser import AmazonEmailParser, ParsedOrder
from email_sender import send_summary_email, send_clarification_email, send_correction_confirmation_email
# Storage no longer needed - using YNAB memo for deduplication
from ynab_client import YNABClient
from ynab_writer import YNABWriter

# Cache for secrets and services
_secrets_cache = {}
_gmail_service = None


def get_secret(secret_id: str) -> str:
    """Fetch secret from Secret Manager (with caching)."""
    if secret_id in _secrets_cache:
        return _secrets_cache[secret_id]

    project_id = os.getenv("GCP_PROJECT_ID")
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{project_id}/secrets/{secret_id}/versions/latest"
    response = client.access_secret_version(request={"name": name})
    secret_value = response.payload.data.decode("UTF-8")
    _secrets_cache[secret_id] = secret_value
    return secret_value


def get_gmail_service():
    """Get authenticated Gmail API service."""
    global _gmail_service
    if _gmail_service:
        return _gmail_service

    from google.auth.transport.requests import Request

    # Get OAuth token from Secret Manager
    token_json = get_secret("gmail-oauth-token")
    token_data = json.loads(token_json)

    creds = Credentials(
        token=token_data.get("token"),
        refresh_token=token_data.get("refresh_token"),
        token_uri=token_data.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=token_data.get("client_id"),
        client_secret=token_data.get("client_secret"),
        scopes=token_data.get("scopes", [
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.send",
        ]),
    )

    # Refresh the token if expired
    if not creds.valid or creds.expired:
        print("Refreshing Gmail OAuth token...")
        creds.refresh(Request())
        print("Token refreshed successfully")

    _gmail_service = build("gmail", "v1", credentials=creds)
    return _gmail_service


def get_ynab_client() -> YNABClient:
    """Get YNAB client with credentials from Secret Manager."""
    token = get_secret("ynab-token")
    return YNABClient(token)


def get_anthropic_client() -> anthropic.Anthropic:
    """Get Anthropic client with credentials from Secret Manager."""
    api_key = get_secret("anthropic-api-key")
    return anthropic.Anthropic(api_key=api_key)


def get_budget_name() -> str:
    """Get YNAB budget name from Secret Manager."""
    return get_secret("ynab-budget-name")


# Amazon payee names to look for in YNAB
AMAZON_PAYEES = [
    "amazon.com", "amazon", "amazon prime", "amazon fresh",
    "whole foods", "whole foods market", "amzn mktp", "amzn digital",
]

GROCERY_PAYEES = ["amazon fresh", "whole foods", "whole foods market"]

# Flag colors for transactions
FLAG_CREATED = "yellow"  # Auto-created from email (no bank match)
FLAG_MATCHED = "orange"  # Matched existing bank transaction


def get_default_account_id(ynab: YNABClient, budget_id: str) -> Optional[str]:
    """Get the default account for Amazon transactions."""
    accounts = ynab.get_accounts(budget_id)

    # First: try secret-configured account name
    try:
        account_name = get_secret("ynab-amazon-account")
        for acc in accounts:
            if acc.get("name", "").lower() == account_name.lower():
                return acc.get("id")
    except Exception:
        pass

    # Second: look for an account with "amazon" in the name
    for acc in accounts:
        if "amazon" in acc.get("name", "").lower() and not acc.get("closed"):
            return acc.get("id")

    # Third: first credit card account
    for acc in accounts:
        if acc.get("type") == "creditCard" and not acc.get("closed"):
            return acc.get("id")

    # Last resort: first non-closed account
    for acc in accounts:
        if not acc.get("closed"):
            return acc.get("id")

    return None


def parsed_order_to_amazon_order(parsed: ParsedOrder) -> AmazonOrder:
    """Convert ParsedOrder to AmazonOrder for categorization."""
    items = [
        AmazonItem(
            order_id=parsed.order_id,
            order_date=parsed.order_date,
            title=item.title,
            category="",
            quantity=item.quantity,
            item_total=item.price or Decimal("0"),
        )
        for item in parsed.items
    ]
    return AmazonOrder(
        order_id=parsed.order_id,
        order_date=parsed.order_date,
        total=parsed.total,
        items=items,
    )


def find_matching_transaction(
    ynab: YNABClient,
    budget_id: str,
    order: AmazonOrder,
    tolerance_days: int = 5,
):
    """Find a YNAB transaction matching this order."""
    since_date = (order.order_date - timedelta(days=tolerance_days)).strftime("%Y-%m-%d")

    transactions = ynab.get_transactions_by_payee(
        budget_id=budget_id,
        payee_names=AMAZON_PAYEES,
        since_date=since_date,
        unapproved_only=True,
    )

    for trans in transactions:
        date_diff = abs((trans.date - order.order_date).days)
        if date_diff > tolerance_days:
            continue
        if abs(abs(trans.amount) - order.total) < Decimal("0.01"):
            return trans

    return None


def apply_categorization(
    ynab: YNABClient,
    budget_id: str,
    transaction,
    result,
    flag_color: str = "orange",
) -> bool:
    """Apply categorization to YNAB transaction."""
    # Build splits from categorization result
    splits = []
    total_assigned = Decimal("0")

    for assignment in result.assignments:
        amount = -abs(assignment.amount)
        # For grocery orders (single "Groceries" category), use simple memo
        if assignment.category_name.lower() == "groceries" and len(result.assignments) == 1:
            memo = "Groceries"
        else:
            memo = ", ".join([i[:20] for i in assignment.items[:3]])
        splits.append({
            "amount": amount,
            "category_id": assignment.category_id,
            "memo": memo,
        })
        total_assigned += amount

    # Ensure splits sum exactly to transaction amount (YNAB requirement)
    transaction_amount = transaction.amount
    if isinstance(transaction_amount, (int, float)):
        transaction_amount = Decimal(str(transaction_amount))

    diff = transaction_amount - total_assigned
    if abs(diff) > Decimal("0.001") and splits:
        # Adjust last split to make totals match
        splits[-1]["amount"] += diff
        print(f"Adjusted last split by {diff} to match transaction total")

    print(f"Applying {len(splits)} splits totaling {total_assigned} to transaction {transaction.transaction_id}")

    try:
        writer = YNABWriter(ynab)
        writer.create_split_transaction(
            budget_id=budget_id,
            transaction_id=transaction.transaction_id,
            splits=splits,
            memo=f"Amazon Order {result.order_id}",
            flag_color=flag_color,
            approved=True,
        )
        return True
    except Exception as e:
        print(f"Error applying categorization: {e}")
        # Log more details
        print(f"  Transaction amount: {transaction_amount}")
        print(f"  Splits total: {total_assigned}")
        print(f"  Splits: {splits}")
        return False


def fetch_email_by_id(gmail_service, msg_id: str) -> Optional[dict]:
    """Fetch a single email by ID."""
    try:
        msg = gmail_service.users().messages().get(
            userId="me",
            id=msg_id,
            format="full"
        ).execute()

        payload = msg.get("payload", {})
        headers = payload.get("headers", [])

        def get_header(name):
            for h in headers:
                if h["name"].lower() == name.lower():
                    return h["value"]
            return ""

        def get_body(payload):
            html_body = ""
            text_body = ""

            def extract(part):
                nonlocal html_body, text_body
                mime = part.get("mimeType", "")
                data = part.get("body", {}).get("data", "")
                if data:
                    decoded = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
                    if mime == "text/html":
                        html_body = decoded
                    elif mime == "text/plain":
                        text_body = decoded
                for p in part.get("parts", []):
                    extract(p)

            extract(payload)
            return html_body, text_body

        html_body, text_body = get_body(payload)

        return {
            "id": msg_id,
            "thread_id": msg.get("threadId"),  # For reply threading
            "message_id": get_header("Message-ID"),
            "subject": get_header("Subject"),
            "from": get_header("From"),
            "to": get_header("To"),
            "date": get_header("Date"),  # Email date with timezone
            "html_body": html_body,
            "text_body": text_body,
        }
    except Exception as e:
        print(f"Error fetching email {msg_id}: {e}")
        return None


def extract_reply_text(email_data: dict) -> str:
    """Extract just the user's reply text, stripping quoted content.

    Args:
        email_data: Dict with 'text_body' and/or 'html_body'

    Returns:
        The user's reply text with quoted content removed
    """
    # Prefer text body for easier parsing
    body = email_data.get("text_body", "") or email_data.get("html_body", "")

    if not body:
        return ""

    # Strip HTML tags if present
    body = re.sub(r'<[^>]+>', '\n', body)
    body = body.replace('&nbsp;', ' ')
    body = body.replace('&lt;', '<').replace('&gt;', '>')

    lines = body.split('\n')
    reply_lines = []

    for line in lines:
        stripped = line.strip()

        # Stop at common reply markers
        if re.match(r'^On .+ wrote:$', stripped):
            break
        if re.match(r'^-+ ?Original Message ?-+$', stripped, re.IGNORECASE):
            break
        if re.match(r'^-+ ?Forwarded message ?-+$', stripped, re.IGNORECASE):
            break
        if re.match(r'^From:', stripped) and len(reply_lines) > 0:
            # "From:" at start of email is OK, but after content it's quoted
            break

        # Skip quoted lines
        if stripped.startswith('>'):
            continue

        reply_lines.append(line)

    # Clean up result
    result = '\n'.join(reply_lines).strip()

    # Remove multiple blank lines
    result = re.sub(r'\n{3,}', '\n\n', result)

    return result


def parse_correction_request(
    reply_text: str,
    categories: list,
    current_splits: list,
    client,
) -> dict:
    """Parse a plain English correction request using Claude.

    Args:
        reply_text: The user's reply text
        categories: List of YNABCategory objects
        current_splits: List of current subtransactions with memo/category
        client: Anthropic client

    Returns:
        Dict with:
        - {"action": "update", "changes": [{"item": "...", "new_category": "..."}]}
        - {"action": "clarify", "options": [...], "pending_category": "..."}
        - {"action": "none", "reason": "..."}
    """
    from config import CLAUDE_MODEL

    # Build category list string
    category_names = [c.name for c in categories]
    categories_str = ", ".join(category_names)

    # Build current splits description
    splits_desc = []
    for split in current_splits:
        memo = split.get("memo", "Unknown item")
        cat_name = split.get("category_name", "Uncategorized")
        amount = split.get("amount", 0)
        # Convert milliunits to dollars
        if isinstance(amount, int):
            amount_dollars = abs(amount) / 1000
        else:
            amount_dollars = abs(float(amount))
        splits_desc.append(f"- {memo}: {cat_name} (${amount_dollars:.2f})")
    splits_str = "\n".join(splits_desc) if splits_desc else "No items found"

    prompt = f"""Parse this categorization correction request.

Available categories: {categories_str}

Current categorization:
{splits_str}

User's message:
{reply_text}

Rules:
1. Match user's category to closest available category (best guess, no confirmation needed)
2. Only ask for clarification if you cannot identify which ITEM the user means
3. If the user just provides a number (like "1" or "2"), this is a response to a previous clarification - parse it as selecting that item number
4. For multiple corrections (e.g., "categorize X as Y and Z as W"), return all changes

Return JSON only:
- Clear: {{"action": "update", "changes": [{{"item": "item substring that matches memo", "new_category": "exact category name"}}]}}
- Ambiguous item: {{"action": "clarify", "options": [{{"num": 1, "item": "full item name", "amount": "$X.XX"}}], "pending_category": "exact category name"}}
- No action needed: {{"action": "none", "reason": "brief explanation"}}

Return ONLY valid JSON, no other text."""

    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}]
    )

    response_text = response.content[0].text.strip()

    # Extract JSON from markdown code blocks if present
    if "```" in response_text:
        response_text = response_text.split("```")[1].split("```")[0]
        if response_text.startswith("json"):
            response_text = response_text[4:]
        response_text = response_text.strip()

    try:
        return json.loads(response_text)
    except json.JSONDecodeError:
        return {"action": "none", "reason": "Could not parse correction request"}


def apply_category_corrections(
    ynab: YNABClient,
    budget_id: str,
    transaction,
    changes: list,
    categories: list,
) -> bool:
    """Apply category corrections by deleting and recreating the transaction.

    YNAB API limitation: category_id cannot be changed on split transactions.
    Workaround: Delete the transaction and recreate it with corrected categories.

    Args:
        ynab: YNAB client
        budget_id: Budget ID
        transaction: YNABTransaction with subtransactions
        changes: List of {"item": "...", "new_category": "..."}
        categories: List of YNABCategory objects for ID lookup

    Returns:
        True if successfully updated
    """
    # Build category name -> ID lookup (case-insensitive)
    cat_lookup = {c.name.lower(): c.category_id for c in categories}

    subtransactions = transaction.subtransactions.copy()
    if not subtransactions:
        print(f"Transaction {transaction.transaction_id} has no subtransactions")
        return False

    changed = False
    for change in changes:
        item_match = change["item"].lower()
        new_category = change["new_category"]

        # Find category ID (case-insensitive, with fuzzy matching)
        new_cat_id = cat_lookup.get(new_category.lower())
        if not new_cat_id:
            # Try fuzzy match
            for cat in categories:
                if new_category.lower() in cat.name.lower() or cat.name.lower() in new_category.lower():
                    new_cat_id = cat.category_id
                    new_category = cat.name  # Use canonical name
                    break

        if not new_cat_id:
            print(f"Category '{new_category}' not found, skipping")
            continue

        # Find and update matching subtransaction
        for i, sub in enumerate(subtransactions):
            memo = sub.get("memo", "").lower()
            if item_match in memo:
                subtransactions[i]["category_id"] = new_cat_id
                changed = True
                print(f"Updated '{sub.get('memo', '')}' to category '{new_category}'")
                break

    if not changed:
        print("No matching items found to update")
        return False

    # Build new subtransactions for recreation
    formatted_subs = []
    for sub in subtransactions:
        amount = sub.get("amount", 0)
        # If already in milliunits (int), keep it; otherwise convert
        if isinstance(amount, (float, Decimal)):
            amount = int(amount * 1000)
        formatted_subs.append({
            "amount": amount,
            "category_id": sub.get("category_id"),
            "memo": sub.get("memo"),
        })
        print(f"  Subtransaction: {sub.get('memo')} -> cat_id={sub.get('category_id')}")

    writer = YNABWriter(ynab)

    # YNAB API limitation: Can't update category_id on split transactions
    # Workaround: Delete and recreate the transaction
    print(f"Deleting transaction {transaction.transaction_id} (YNAB API limitation workaround)")
    try:
        writer.delete_transaction(budget_id, transaction.transaction_id)
    except Exception as e:
        print(f"Error deleting transaction: {e}")
        return False

    # Recreate with corrected categories
    print(f"Recreating transaction with {len(formatted_subs)} subtransactions")
    try:
        # transaction.amount is already in dollars (Decimal), create_transaction will convert
        result = writer.create_transaction(
            budget_id=budget_id,
            account_id=transaction.account_id,
            date=transaction.date.strftime("%Y-%m-%d"),
            amount=transaction.amount,  # Decimal in dollars
            payee_name=transaction.payee_name,
            memo=transaction.memo,
            flag_color=transaction.flag_color,
            approved=transaction.approved,
            subtransactions=formatted_subs,
        )
        print(f"YNAB create result: {result}")
        return True
    except Exception as e:
        print(f"Error recreating transaction: {e}")
        import traceback
        traceback.print_exc()
        return False


def update_category_cache_from_corrections(changes: list, subtransactions: list) -> None:
    """Update the category cache based on corrections.

    This ensures future orders with the same items get the correct category.

    Args:
        changes: List of {"item": "...", "new_category": "..."}
        subtransactions: List of subtransaction dicts with memo field
    """
    from utils import cache_category, save_category_cache

    for change in changes:
        item_match = change["item"].lower()
        new_category = change["new_category"]

        # Find the full item name from subtransaction memo
        for sub in subtransactions:
            memo = sub.get("memo", "")
            if item_match in memo.lower():
                # Cache with the full memo (item description)
                cache_category(memo, new_category)
                print(f"Cached: '{memo}' -> '{new_category}'")
                break

    # Save cache to disk
    save_category_cache()


def process_correction_reply(
    gmail_service,
    email_data: dict,
    order_id: str,
) -> dict:
    """Process a reply email as a categorization correction.

    Args:
        gmail_service: Authenticated Gmail service
        email_data: Email data dict with text_body, html_body, etc.
        order_id: Amazon order ID extracted from subject

    Returns:
        Dict with status and message
    """
    # Skip if this is FROM our receipts email (it's our own automated reply)
    from_addr = email_data.get("from", "").lower()
    try:
        from config_private import RECEIPTS_EMAIL
        receipts_email = RECEIPTS_EMAIL.lower()
    except ImportError:
        receipts_email = ""  # No receipts email configured

    if receipts_email in from_addr:
        return {"status": "skipped", "message": "Skipping our own automated reply"}

    # Atomically claim this email to prevent duplicate processing
    email_id = email_data.get("id")
    if email_id and not mark_email_processed(email_id, order_id):
        return {"status": "skipped", "message": f"Email {email_id} already being processed"}

    # Extract the reply text
    reply_text = extract_reply_text(email_data)
    if not reply_text or len(reply_text.strip()) < 3:
        return {"status": "skipped", "message": "No reply text found"}

    print(f"Processing correction for order {order_id}: '{reply_text[:50]}...'")

    # Get YNAB client and find the transaction
    ynab = get_ynab_client()
    budget_name = get_budget_name()
    budget_id = ynab.get_budget_id(budget_name)

    if not budget_id:
        return {"status": "error", "message": f"Budget '{budget_name}' not found"}

    # Find the transaction by order ID (search last 90 days)
    from datetime import timedelta
    since_date = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
    transaction = ynab.find_transaction_by_order_id(budget_id, order_id, since_date=since_date)

    if not transaction:
        # Send error reply
        send_summary_email(
            gmail_service=gmail_service,
            to=[email_data.get("from", "")],
            order_id=order_id,
            order_total=Decimal("0"),
            error=f"Could not find transaction for order {order_id}",
            in_reply_to=email_data.get("message_id"),
            original_subject=email_data.get("subject"),
            thread_id=email_data.get("thread_id"),
        )
        return {"status": "error", "message": f"Transaction not found for order {order_id}"}

    # Get categories for parsing
    all_categories = ynab.get_categories(budget_id)
    excluded_groups = ['library renovation']
    categories = [c for c in all_categories if c.group_name.lower() not in excluded_groups]

    # Build current splits info with category names
    cat_id_to_name = {c.category_id: c.name for c in categories}
    current_splits = []
    for sub in transaction.subtransactions:
        cat_id = sub.get("category_id")
        current_splits.append({
            "memo": sub.get("memo", ""),
            "category_name": cat_id_to_name.get(cat_id, "Uncategorized"),
            "amount": sub.get("amount", 0),
        })

    # Parse the correction request with Claude
    claude = get_anthropic_client()
    parsed = parse_correction_request(reply_text, categories, current_splits, claude)

    print(f"Parsed correction: {parsed}")

    # Extract sender for TO, receipts inbox for CC
    from_addr = email_data.get("from", "")
    sender_email = None
    if from_addr and "@" in from_addr:
        if "<" in from_addr and ">" in from_addr:
            match = re.search(r'<([^>]+)>', from_addr)
            sender_email = match.group(1) if match else from_addr
        else:
            sender_email = from_addr

    # Get receipts email for CC
    try:
        from config_private import RECEIPTS_EMAIL
        receipts_email = RECEIPTS_EMAIL
    except ImportError:
        receipts_email = None

    # Build recipients: sender in TO, receipts inbox in CC
    recipients = [sender_email] if sender_email else []
    cc_recipients = [receipts_email] if receipts_email and receipts_email.lower() != (sender_email or "").lower() else []

    print(f"Correction reply - TO: {recipients}, CC: {cc_recipients} (from: {from_addr})")

    # Handle the parsed result
    if parsed.get("action") == "clarify":
        # Send clarification email
        send_clarification_email(
            gmail_service=gmail_service,
            to=recipients,
            order_id=order_id,
            options=parsed.get("options", []),
            pending_category=parsed.get("pending_category", ""),
            in_reply_to=email_data.get("message_id"),
            original_subject=email_data.get("subject"),
            thread_id=email_data.get("thread_id"),
        )
        return {"status": "clarification_sent", "message": "Asked for clarification"}

    elif parsed.get("action") == "update":
        changes = parsed.get("changes", [])
        if not changes:
            return {"status": "error", "message": "No changes to apply"}

        # Apply the corrections
        success = apply_category_corrections(
            ynab=ynab,
            budget_id=budget_id,
            transaction=transaction,
            changes=changes,
            categories=categories,
        )

        if not success:
            send_summary_email(
                gmail_service=gmail_service,
                to=recipients,
                order_id=order_id,
                order_total=abs(transaction.amount),
                error="Failed to apply corrections",
                in_reply_to=email_data.get("message_id"),
                original_subject=email_data.get("subject"),
                thread_id=email_data.get("thread_id"),
            )
            return {"status": "error", "message": "Failed to apply corrections"}

        # Update the category cache for future orders
        update_category_cache_from_corrections(changes, transaction.subtransactions)

        # Fetch the updated transaction
        updated_transaction = ynab.get_transaction_by_id(budget_id, transaction.transaction_id)
        if not updated_transaction:
            updated_transaction = transaction

        # YNAB API may have eventual consistency - manually apply our changes to category names
        # Build a map of item -> new category from our changes
        item_to_new_cat = {}
        for change in changes:
            item_match = change["item"].lower()
            item_to_new_cat[item_match] = change["new_category"]

        # Update category names in subtransactions based on our changes
        for sub in updated_transaction.subtransactions:
            memo = sub.get("memo", "").lower()
            for item_match, new_cat in item_to_new_cat.items():
                if item_match in memo:
                    sub["category_name"] = new_cat
                    break

        # Log for debugging
        print(f"Updated transaction has {len(updated_transaction.subtransactions)} subtransactions")
        for sub in updated_transaction.subtransactions:
            print(f"  - {sub.get('memo', 'no memo')[:20]}: {sub.get('category_name', 'no cat name')}")

        # Build YNAB URL
        ynab_url = None
        if transaction.account_id:
            ynab_url = f"https://app.ynab.com/{budget_id}/accounts/{transaction.account_id}"

        # Send confirmation with full updated categorization
        send_correction_confirmation_email(
            gmail_service=gmail_service,
            to=recipients,
            order_id=order_id,
            transaction=updated_transaction,
            in_reply_to=email_data.get("message_id"),
            original_subject=email_data.get("subject"),
            thread_id=email_data.get("thread_id"),
            ynab_url=ynab_url,
            cc=cc_recipients,
            changes=changes,
        )

        return {
            "status": "updated",
            "message": f"Applied {len(changes)} correction(s) to order {order_id}",
            "changes": changes,
        }

    else:
        # No action needed
        reason = parsed.get("reason", "No correction identified")
        return {"status": "no_action", "message": reason}


def get_stored_history_id() -> Optional[str]:
    """Get the last processed history ID from Firestore."""
    try:
        from google.cloud import firestore
        db = firestore.Client(project=os.getenv("GCP_PROJECT_ID"))
        doc = db.collection("config").document("gmail_history").get()
        if doc.exists:
            return doc.to_dict().get("history_id")
    except Exception as e:
        print(f"Error getting stored history ID: {e}")
    return None


def save_history_id(history_id: str) -> None:
    """Save the last processed history ID to Firestore."""
    from api_writer import save_history_id as _save_history_id
    _save_history_id(history_id, os.getenv("GCP_PROJECT_ID"))


def is_email_processed(email_id: str) -> bool:
    """Check if an email has already been processed (prevents race conditions)."""
    try:
        from google.cloud import firestore
        db = firestore.Client(project=os.getenv("GCP_PROJECT_ID"))
        doc = db.collection("processed_emails").document(email_id).get()
        return doc.exists
    except Exception as e:
        print(f"Error checking processed email: {e}")
        return False


def mark_email_processed(email_id: str, order_id: str) -> bool:
    """Mark an email as processed. Returns False if already processed (race condition)."""
    from api_writer import mark_email_processed as _mark_email_processed
    return _mark_email_processed(email_id, order_id, os.getenv("GCP_PROJECT_ID"))


def get_watch_expiration() -> Optional[int]:
    """Get the Gmail watch expiration timestamp from Firestore."""
    try:
        from google.cloud import firestore
        db = firestore.Client(project=os.getenv("GCP_PROJECT_ID"))
        doc = db.collection("config").document("gmail_watch").get()
        if doc.exists:
            return doc.to_dict().get("expiration")
    except Exception as e:
        print(f"Error getting watch expiration: {e}")
    return None


def save_watch_expiration(expiration: int) -> None:
    """Save the Gmail watch expiration timestamp to Firestore."""
    from api_writer import save_watch_expiration as _save_watch_expiration
    _save_watch_expiration(expiration, os.getenv("GCP_PROJECT_ID"))


def renew_gmail_watch_if_needed(gmail_service) -> None:
    """Renew Gmail watch if it's close to expiring (within 1 day)."""
    from api_writer import setup_gmail_watch
    try:
        expiration = get_watch_expiration()
        now_ms = int(datetime.now().timestamp() * 1000)
        one_day_ms = 24 * 60 * 60 * 1000

        # Renew if no expiration stored or within 1 day of expiring
        if expiration is None or (expiration - now_ms) < one_day_ms:
            print("Gmail watch expiring soon or unknown, renewing...")

            project_id = os.getenv("GCP_PROJECT_ID")
            response = setup_gmail_watch(gmail_service, project_id, "amazon-receipts")
            new_expiration = int(response.get("expiration", 0))
            save_watch_expiration(new_expiration)
            print(f"Gmail watch renewed, new expiration: {new_expiration}")
        else:
            days_left = (expiration - now_ms) / one_day_ms
            print(f"Gmail watch OK, {days_left:.1f} days until expiration")
    except Exception as e:
        print(f"Error checking/renewing Gmail watch: {e}")


def fetch_emails_from_history(gmail_service, notification_history_id: str) -> list:
    """
    Fetch emails using History API.

    The notification's historyId is the LATEST ID - nothing after it.
    We need to query from our STORED history ID to get changes.
    Then update stored ID to the notification's ID.
    """
    stored_history_id = get_stored_history_id()

    if not stored_history_id:
        # First run - save current ID and skip (no previous baseline)
        print(f"No stored history ID, initializing to {notification_history_id}")
        save_history_id(notification_history_id)
        return []

    print(f"Fetching history from {stored_history_id} to {notification_history_id}")

    new_message_ids = set()

    # If history IDs match, we can't get changes from history API - fetch recent messages instead
    if stored_history_id == notification_history_id:
        print("History IDs match - checking recent INBOX messages")
        try:
            # Get messages from the last hour
            import time
            one_hour_ago = int(time.time()) - 3600
            recent_msgs = gmail_service.users().messages().list(
                userId="me",
                labelIds=["INBOX"],
                q=f"after:{one_hour_ago}",
                maxResults=10,
            ).execute()

            for msg in recent_msgs.get("messages", []):
                msg_id = msg.get("id")
                # Check if we've already processed this message
                if msg_id and not is_email_processed(msg_id):
                    new_message_ids.add(msg_id)
                    print(f"Found unprocessed recent message: {msg_id}")
        except Exception as e:
            print(f"Error fetching recent messages: {e}")
    else:
        # Normal path - use history API
        try:
            history = gmail_service.users().history().list(
                userId="me",
                startHistoryId=stored_history_id,
                historyTypes=["messageAdded"],
                labelId="INBOX",  # Only get messages added to INBOX
            ).execute()

            # Extract message IDs from messagesAdded events
            for record in history.get("history", []):
                for msg in record.get("messagesAdded", []):
                    msg_id = msg.get("message", {}).get("id")
                    if msg_id:
                        new_message_ids.add(msg_id)
        except Exception as e:
            print(f"Error fetching history: {e}")

    if not new_message_ids:
        print("No new messages in history")
        save_history_id(notification_history_id)  # Update pointer
        return []

    print(f"Found {len(new_message_ids)} new message(s): {list(new_message_ids)}")

    # Fetch each message and filter for Amazon emails
    emails = []
    for msg_id in new_message_ids:
        email = fetch_email_by_id(gmail_service, msg_id)
        if not email:
            continue

        subject = email.get("subject", "")
        subject_lower = subject.lower()
        from_addr = email.get("from", "").lower()

        # Check if this is a reply - could be a correction request
        if subject_lower.startswith("re:"):
            # Look for order ID in the thread
            thread_id = email.get("thread_id")
            order_id = None

            if thread_id:
                try:
                    thread = gmail_service.users().threads().get(
                        userId="me",
                        id=thread_id,
                        format="minimal"
                    ).execute()
                    # Search all messages in thread for order ID
                    for thread_msg in thread.get("messages", []):
                        snippet = thread_msg.get("snippet", "")
                        order_match = re.search(r'(\d{3}-\d{7}-\d{7})', snippet)
                        if order_match:
                            order_id = order_match.group(1)
                            break
                except Exception as e:
                    print(f"Error fetching thread {thread_id}: {e}")

            if order_id:
                # This is a reply in a categorization thread - process as correction
                email["_is_correction"] = True
                email["_order_id"] = order_id
                emails.append(email)
                print(f"Found reply in order thread {order_id}: {subject[:50]}")
            else:
                print(f"Skipping reply (no order ID in thread): {subject[:50]}")
            continue

        # Skip emails sent from the receipts inbox (our own emails)
        # Import receipts email from config (falls back to checking email_address from notification)
        try:
            from config_private import RECEIPTS_EMAIL
            receipts_email = RECEIPTS_EMAIL.lower()
        except ImportError:
            receipts_email = email_address.lower() if email_address else ""

        if receipts_email and receipts_email in from_addr:
            print(f"Skipping self-sent: {subject[:50]}")
            continue

        # Check if Amazon-related
        body = (email.get("html_body", "") + email.get("text_body", "")).lower()
        is_amazon = (
            "amazon.com" in from_addr or
            ("amazon" in body and ("order" in subject_lower or "shipped" in subject_lower or "ordered" in subject_lower))
        )

        if is_amazon:
            emails.append(email)
            print(f"Found Amazon email: {subject[:50]} (id: {msg_id})")
        else:
            print(f"Skipping non-Amazon: {subject[:50]}")

    # Save the notification's history ID for next time
    save_history_id(notification_history_id)
    return emails


def process_email_and_reply(
    email_data: dict,
    gmail_service,
    reply_to: Optional[str] = None,
    receipts_email: Optional[str] = None,
) -> dict:
    """
    Process a single Amazon email and send a reply summary.

    Args:
        email_data: Dict with 'html_body', 'text_body', 'subject', 'message_id', 'from', 'thread_id'
        gmail_service: Authenticated Gmail service for sending reply
        reply_to: Email address of the person who forwarded (to reply to)
        receipts_email: The receipts inbox email (for CC)

    Returns:
        Dict with processing result
    """
    thread_id = email_data.get("thread_id")
    claude = get_anthropic_client()
    parser = AmazonEmailParser(client=claude)

    # Parse original email date from forwarded message
    from zoneinfo import ZoneInfo
    from email.utils import parsedate_to_datetime

    eastern = ZoneInfo("America/New_York")

    def extract_original_date(email_data: dict) -> Optional[datetime]:
        """Extract the original email date from a forwarded message."""
        # Look for "Date:" in the forwarded message header block
        # Gmail format: "---------- Forwarded message ---------\nFrom: ...\nDate: Fri, Jan 10, 2025 at 3:45 PM\n..."
        body = email_data.get("text_body", "") or email_data.get("html_body", "")

        # Try to find Date: line in forwarded header
        date_match = re.search(r'Date:\s*(.+?)(?:\n|<br|$)', body, re.IGNORECASE)
        if date_match:
            date_str = date_match.group(1).strip()
            # Clean up HTML entities and tags
            date_str = re.sub(r'<[^>]+>', '', date_str)
            date_str = date_str.replace('&nbsp;', ' ').strip()
            try:
                # Try standard email date format first
                return parsedate_to_datetime(date_str)
            except Exception:
                # Try common Gmail forward format: "Fri, Jan 10, 2025 at 3:45 PM"
                try:
                    # Remove "at" and parse
                    date_str = date_str.replace(' at ', ' ')
                    from dateutil import parser as date_parser
                    return date_parser.parse(date_str)
                except Exception:
                    pass
        return None

    # Try to get original email date, fall back to forward date, then current time
    email_datetime = extract_original_date(email_data)
    if email_datetime:
        print(f"Using original email date: {email_datetime}")
    else:
        # Fall back to the forward's Date header
        email_date_str = email_data.get("date", "")
        try:
            if email_date_str:
                email_datetime = parsedate_to_datetime(email_date_str)
                print(f"Using forward date: {email_datetime}")
            else:
                email_datetime = datetime.now(eastern)
                print(f"No date found, using current Eastern time: {email_datetime}")
        except Exception as e:
            print(f"Error parsing date '{email_date_str}': {e}, using Eastern time")
            email_datetime = datetime.now(eastern)

    # Create a minimal RawEmail-like object for parsing
    class EmailWrapper:
        def __init__(self, data, parsed_date):
            self.uid = data.get("id", "")
            self.message_id = data.get("message_id", "")
            self.subject = data.get("subject", "")
            self.from_addr = data.get("from", "")
            self.date = parsed_date
            self.html_body = data.get("html_body", "")
            self.text_body = data.get("text_body", "")

    email = EmailWrapper(email_data, email_datetime)
    try:
        parsed = parser.parse_email(email)
    except Exception as e:
        error_str = str(e)
        if "ANTHROPIC_ERROR:quota_exhausted" in error_str:
            print("ALERT: Anthropic API quota exhausted!")
            return {"status": "error", "message": "Anthropic quota exhausted - please add credits", "alert": True}
        elif "ANTHROPIC_ERROR:rate_limited" in error_str:
            print("ALERT: Anthropic API rate limited!")
            return {"status": "error", "message": "Anthropic rate limited - try again later", "alert": True}
        raise

    if not parsed:
        return {"status": "error", "message": "Could not parse email"}

    # Atomically claim this email to prevent race condition duplicates
    email_id = email_data.get("id")
    if email_id and not mark_email_processed(email_id, parsed.order_id):
        return {"status": "skipped", "message": f"Email {email_id} already being processed"}

    # Build list of recipients for reply (forwarder + receipts inbox)
    recipients = []
    if reply_to:
        recipients.append(reply_to)
    if receipts_email and receipts_email not in recipients:
        recipients.append(receipts_email)

    # Check YNAB directly for existing order (by memo containing order ID)
    ynab = get_ynab_client()
    budget_name = get_budget_name()
    budget_id = ynab.get_budget_id(budget_name)

    if not budget_id:
        error_msg = f"Budget '{budget_name}' not found"
        if gmail_service and recipients:
            send_summary_email(
                gmail_service=gmail_service,
                to=recipients,
                order_id=parsed.order_id,
                order_total=parsed.total,
                error=error_msg,
                in_reply_to=email_data.get("message_id"),
                original_subject=email_data.get("subject"),
                thread_id=thread_id,
            )
        return {"status": "error", "message": error_msg}

    # Check if order already exists in YNAB by looking for memo with order ID
    since_date = (email_datetime - timedelta(days=30)).strftime("%Y-%m-%d")
    existing = ynab.find_transaction_by_memo(budget_id, parsed.order_id, since_date=since_date)
    if existing:
        # Verify the transaction still exists (might have been deleted)
        if ynab.transaction_exists(budget_id, existing.transaction_id):
            return {"status": "skipped", "message": f"Order {parsed.order_id} already in YNAB (transaction {existing.transaction_id})"}
        else:
            print(f"Found memo match but transaction {existing.transaction_id} was deleted - proceeding")

    print(f"Processing order {parsed.order_id} - ${parsed.total}")

    order = parsed_order_to_amazon_order(parsed)

    # Use date from original email (forwarded email's Date header)
    transaction_date = email_datetime.strftime("%Y-%m-%d")
    transaction = find_matching_transaction(ynab, budget_id, order)

    result: Optional[CategorizationResult] = None

    # Get categories for categorization (exclude certain groups)
    all_categories = ynab.get_categories(budget_id)
    excluded_groups = ['library renovation']
    categories = [c for c in all_categories
                  if c.group_name.lower() not in excluded_groups]

    # Determine flag color based on whether we matched or created
    if transaction:
        # Verify the transaction still exists (might have been deleted)
        if not ynab.transaction_exists(budget_id, transaction.transaction_id):
            print(f"Matched transaction {transaction.transaction_id} no longer exists - will create new")
            transaction = None

    if transaction:
        print(f"Found matching transaction: ${abs(transaction.amount)} on {transaction.date}")
        flag_color = FLAG_MATCHED
    else:
        print(f"No matching YNAB transaction for order {parsed.order_id} - creating new transaction")
        # Create a new transaction
        account_id = get_default_account_id(ynab, budget_id)
        if not account_id:
            error_msg = "No account found to create transaction"
            print(error_msg)
            return {"status": "error", "message": error_msg}

        writer = YNABWriter(ynab)
        created = writer.create_transaction(
            budget_id=budget_id,
            account_id=account_id,
            date=transaction_date,  # Use Eastern time
            amount=-parsed.total,  # Negative for outflow
            payee_name="Amazon.com",
            memo=f"Order {parsed.order_id}",
            flag_color=FLAG_CREATED,  # Yellow flag for auto-created
            approved=False,
        )
        if not created or not created.get("id"):
            error_msg = f"Failed to create transaction for order {parsed.order_id}"
            print(error_msg)
            return {"status": "error", "message": error_msg}

        # Create a transaction-like object for categorization
        from dataclasses import dataclass

        @dataclass
        class CreatedTransaction:
            transaction_id: str
            amount: Decimal
            date: datetime
            payee_name: str
            account_id: str

        transaction = CreatedTransaction(
            transaction_id=created["id"],
            amount=-parsed.total,
            date=parsed.order_date,
            payee_name="Amazon.com",
            account_id=account_id,
        )
        flag_color = FLAG_CREATED
        print(f"Created transaction {transaction.transaction_id}")

    # Check if this is a grocery order (Whole Foods, Amazon Fresh)
    subject_lower = email_data.get("subject", "").lower()
    from_lower = email_data.get("from", "").lower()
    is_grocery = any(
        grocery in subject_lower or grocery in from_lower
        for grocery in GROCERY_PAYEES
    )

    if is_grocery:
        # Find Groceries category
        groceries_cat = next(
            (c for c in categories if c.name.lower() == "groceries"),
            None
        )
        if groceries_cat:
            print(f"Grocery order detected - categorizing as Groceries")
            result = categorize_simple(order, groceries_cat.category_id, groceries_cat.name)
        else:
            print(f"Grocery order but no Groceries category found - using AI categorization")
            result = categorize_order(order=order, categories=categories, client=claude)
    else:
        # Categorize the order using AI
        result = categorize_order(order=order, categories=categories, client=claude)

    # Apply to YNAB
    if apply_categorization(ynab, budget_id, transaction, result, flag_color=flag_color):
        # Build YNAB account URL (YNAB doesn't support deep links to individual transactions)
        ynab_url = None
        if hasattr(transaction, 'account_id') and transaction.account_id:
            ynab_url = f"https://app.ynab.com/{budget_id}/accounts/{transaction.account_id}"

        # Send success email to both forwarder and receipts inbox
        if gmail_service and recipients:
            send_summary_email(
                gmail_service=gmail_service,
                to=recipients,
                order_id=parsed.order_id,
                order_total=parsed.total,
                result=result,
                matched=True,
                in_reply_to=email_data.get("message_id"),
                original_subject=email_data.get("subject"),
                thread_id=thread_id,
                ynab_url=ynab_url,
            )

        return {
            "status": "categorized",
            "message": f"Order {parsed.order_id} categorized and applied to YNAB",
            "order_id": parsed.order_id,
            "transaction_id": transaction.transaction_id,
        }
    else:
        error_msg = f"Failed to apply categorization for {parsed.order_id}"

        if gmail_service and recipients:
            send_summary_email(
                gmail_service=gmail_service,
                to=recipients,
                order_id=parsed.order_id,
                order_total=parsed.total,
                error=error_msg,
                in_reply_to=email_data.get("message_id"),
                original_subject=email_data.get("subject"),
                thread_id=thread_id,
            )

        return {"status": "error", "message": error_msg}


@functions_framework.cloud_event
def process_gmail_push(cloud_event: CloudEvent) -> None:
    """
    Cloud Function triggered by Gmail Pub/Sub push notification.
    """
    # Decode the Pub/Sub message
    data = base64.b64decode(cloud_event.data["message"]["data"]).decode("utf-8")
    message = json.loads(data)

    print(f"Received Gmail notification: {message}")

    history_id = message.get("historyId")
    email_address = message.get("emailAddress")

    print(f"New mail for {email_address}, history ID: {history_id}")

    # Get Gmail service
    try:
        gmail_service = get_gmail_service()
    except Exception as e:
        print(f"Error getting Gmail service: {e}")
        return

    # Auto-renew Gmail watch if close to expiring
    renew_gmail_watch_if_needed(gmail_service)

    # Fetch emails from history using the notification's historyId
    # YNAB memo check will skip already-processed orders
    emails = fetch_emails_from_history(gmail_service, history_id)
    print(f"Processing {len(emails)} Amazon email(s)")

    # Process each email
    for email_data in emails:
        email_id = email_data.get("id")

        # Check if this is a correction reply
        if email_data.get("_is_correction"):
            order_id = email_data.get("_order_id")
            print(f"Processing correction reply for order {order_id}")
            result = process_correction_reply(
                gmail_service=gmail_service,
                email_data=email_data,
                order_id=order_id,
            )
            print(f"Correction result: {result}")
            continue

        # Check if already processed (prevents race condition duplicates)
        if is_email_processed(email_id):
            print(f"Skipping already processed email: {email_id}")
            continue

        # Extract forwarder's email address
        from_addr = email_data.get("from", "")
        forwarder_email = None
        if from_addr and "@" in from_addr:
            # Extract email from "Name <email>" format if needed
            if "<" in from_addr and ">" in from_addr:
                match = re.search(r'<([^>]+)>', from_addr)
                forwarder_email = match.group(1) if match else from_addr
            else:
                forwarder_email = from_addr

        result = process_email_and_reply(
            email_data=email_data,
            gmail_service=gmail_service,
            reply_to=forwarder_email,  # Person who forwarded
            receipts_email=email_address,  # Receipts inbox for visibility
        )
        print(f"Processed email: {result}")


# OAuth configuration
OAUTH_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]
OAUTH_REDIRECT_PATH = "/oauth_callback"


def get_oauth_credentials():
    """Get OAuth client credentials from Secret Manager."""
    try:
        creds_json = get_secret("gmail-oauth-credentials")
        creds = json.loads(creds_json)
        return creds.get("client_id"), creds.get("client_secret")
    except Exception as e:
        print(f"Error getting OAuth credentials: {e}")
        return None, None


@functions_framework.http
def oauth_start(request):
    """
    Start the OAuth flow by redirecting to Google's authorization page.
    """
    from urllib.parse import urlencode
    import secrets

    client_id, _ = get_oauth_credentials()
    if not client_id:
        return {"error": "OAuth not configured"}, 500

    # Build the redirect URI (this function's URL with callback path)
    # Get the host from the request or use configured value
    project_id = os.getenv("GCP_PROJECT_ID")
    region = os.getenv("FUNCTION_REGION", "us-central1")
    redirect_uri = f"https://{region}-{project_id}.cloudfunctions.net/oauth_callback"

    # Generate state for CSRF protection
    state = secrets.token_urlsafe(32)

    # Store state in Firestore for validation (expires in 10 minutes)
    try:
        from google.cloud import firestore
        db = firestore.Client(project=project_id)
        db.collection("oauth_states").document(state).set({
            "created": datetime.now().isoformat(),
            "valid": True,
        })
    except Exception as e:
        print(f"Error storing OAuth state: {e}")

    # Build authorization URL
    auth_params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(OAUTH_SCOPES),
        "access_type": "offline",  # Get refresh token
        "prompt": "consent",  # Always show consent to get refresh token
        "state": state,
    }

    auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(auth_params)}"

    # Redirect to Google
    return "", 302, {"Location": auth_url}


@functions_framework.http
def oauth_callback(request):
    """
    Handle OAuth callback from Google.
    Exchanges authorization code for tokens and stores them.
    """
    import requests as http_requests

    # Check for errors
    error = request.args.get("error")
    if error:
        return f"""
        <html><body>
        <h1>Authorization Failed</h1>
        <p>Error: {error}</p>
        <p><a href="https://charliesneath.github.io/ynab-toolkit/">Return to YNAB Toolkit</a></p>
        </body></html>
        """, 400

    code = request.args.get("code")
    state = request.args.get("state")

    if not code:
        return {"error": "No authorization code received"}, 400

    # Validate state (CSRF protection)
    project_id = os.getenv("GCP_PROJECT_ID")
    try:
        from google.cloud import firestore
        db = firestore.Client(project=project_id)
        state_doc = db.collection("oauth_states").document(state).get()
        if not state_doc.exists or not state_doc.to_dict().get("valid"):
            return {"error": "Invalid state parameter"}, 400
        # Invalidate the state
        db.collection("oauth_states").document(state).delete()
    except Exception as e:
        print(f"Error validating state: {e}")
        # Continue anyway for now - state validation is defense in depth

    # Get OAuth credentials
    client_id, client_secret = get_oauth_credentials()
    if not client_id or not client_secret:
        return {"error": "OAuth not configured"}, 500

    # Build redirect URI (must match exactly)
    region = os.getenv("FUNCTION_REGION", "us-central1")
    redirect_uri = f"https://{region}-{project_id}.cloudfunctions.net/oauth_callback"

    # Exchange code for tokens
    token_response = http_requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        },
    )

    if token_response.status_code != 200:
        print(f"Token exchange failed: {token_response.text}")
        return f"""
        <html><body>
        <h1>Authorization Failed</h1>
        <p>Could not exchange authorization code for tokens.</p>
        <p><a href="https://charliesneath.github.io/ynab-toolkit/">Return to YNAB Toolkit</a></p>
        </body></html>
        """, 400

    tokens = token_response.json()

    # Build the token object matching the expected format
    token_data = {
        "token": tokens.get("access_token"),
        "refresh_token": tokens.get("refresh_token"),
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": client_id,
        "client_secret": client_secret,
        "scopes": OAUTH_SCOPES,
    }

    # Store in Secret Manager (update existing secret)
    try:
        from google.cloud import secretmanager
        client = secretmanager.SecretManagerServiceClient()
        parent = f"projects/{project_id}/secrets/gmail-oauth-token"

        # Add new version
        client.add_secret_version(
            request={
                "parent": parent,
                "payload": {"data": json.dumps(token_data).encode("UTF-8")},
            }
        )
        print("Stored new OAuth token in Secret Manager")

        # Clear the cached token so next request uses new one
        global _gmail_service, _secrets_cache
        _gmail_service = None
        if "gmail-oauth-token" in _secrets_cache:
            del _secrets_cache["gmail-oauth-token"]

    except Exception as e:
        print(f"Error storing token: {e}")
        return f"""
        <html><body>
        <h1>Authorization Succeeded, but Token Storage Failed</h1>
        <p>Error: {e}</p>
        <p>Please try again or contact support.</p>
        </body></html>
        """, 500

    # Set up Gmail watch
    try:
        gmail_service = get_gmail_service()
        from api_writer import setup_gmail_watch
        response = setup_gmail_watch(gmail_service, project_id, "amazon-receipts")
        save_watch_expiration(int(response.get("expiration", 0)))
        watch_status = "Gmail notifications enabled!"
    except Exception as e:
        print(f"Error setting up Gmail watch: {e}")
        watch_status = f"Warning: Could not set up Gmail notifications: {e}"

    return f"""
    <html>
    <head>
        <title>Connected - YNAB Toolkit</title>
        <style>
            body {{ font-family: -apple-system, system-ui, sans-serif; max-width: 600px; margin: 50px auto; padding: 20px; }}
            .success {{ color: #059669; }}
            .warning {{ color: #d97706; }}
            a {{ color: #2563eb; }}
        </style>
    </head>
    <body>
        <h1 class="success">Gmail Connected Successfully!</h1>
        <p>{watch_status}</p>
        <p>Your Amazon order emails will now be automatically categorized in YNAB.</p>
        <p><a href="https://charliesneath.github.io/ynab-toolkit/">Return to YNAB Toolkit</a></p>
    </body>
    </html>
    """, 200


@functions_framework.http
def renew_gmail_watch(request):
    """
    HTTP endpoint to renew Gmail watch.
    Called by Cloud Scheduler every 6 days to prevent expiration.
    """
    from api_writer import setup_gmail_watch
    try:
        gmail_service = get_gmail_service()
        project_id = os.getenv("GCP_PROJECT_ID")

        response = setup_gmail_watch(gmail_service, project_id, "amazon-receipts")

        new_expiration = int(response.get("expiration", 0))
        save_watch_expiration(new_expiration)

        return {
            "status": "renewed",
            "historyId": response.get("historyId"),
            "expiration": new_expiration
        }, 200
    except Exception as e:
        print(f"Error renewing Gmail watch: {e}")
        return {"status": "error", "message": str(e)}, 500


@functions_framework.http
def process_email_http(request):
    """
    HTTP endpoint to process an email directly.
    Useful for testing or manual triggers.

    POST body: {"html_body": "...", "subject": "...", "message_id": "..."}
    """
    if request.method != "POST":
        return {"error": "POST required"}, 405

    email_data = request.get_json()
    if not email_data:
        return {"error": "JSON body required"}, 400

    try:
        gmail_service = get_gmail_service()
    except Exception as e:
        gmail_service = None
        print(f"Gmail service not available: {e}")

    result = process_email_and_reply(
        email_data=email_data,
        gmail_service=gmail_service,
        reply_to=email_data.get("reply_to"),
    )
    return result, 200
