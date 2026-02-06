"""Send email summaries via Gmail API."""

import base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional, List, Dict
from decimal import Decimal

from categorizer import CategorizationResult
from ynab_client import YNABTransaction


def format_summary_email(
    order_id: str,
    order_total: Decimal,
    result: Optional[CategorizationResult],
    matched: bool,
    error: Optional[str] = None,
    ynab_url: Optional[str] = None,
) -> str:
    """
    Format a summary email for an itemized order.

    Returns HTML email body.
    """
    if error:
        return f"""
<html>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px;">
<h2>❌ Error Processing Order</h2>
<p><strong>Order:</strong> #{order_id}</p>
<p><strong>Total:</strong> ${order_total:.2f}</p>
<p><strong>Error:</strong> {error}</p>
</body>
</html>
"""

    if not matched:
        return f"""
<html>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px;">
<h2>📦 Order Received - Pending YNAB Match</h2>
<p><strong>Order:</strong> #{order_id}</p>
<p><strong>Total:</strong> ${order_total:.2f}</p>
<p>No matching YNAB transaction found yet. The order has been saved and will be matched when the transaction appears (usually 1-2 days).</p>
</body>
</html>
"""

    if not result:
        return f"""
<html>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px;">
<h2>📦 Order Stored</h2>
<p><strong>Order:</strong> #{order_id}</p>
<p><strong>Total:</strong> ${order_total:.2f}</p>
</body>
</html>
"""

    # Build categorization summary
    categories_html = ""
    for assignment in result.assignments:
        items_list = ", ".join(assignment.items[:5])
        if len(assignment.items) > 5:
            items_list += f" (+{len(assignment.items) - 5} more)"

        categories_html += f"""
<tr>
    <td style="padding: 8px; border-bottom: 1px solid #eee;"><strong>{assignment.category_name}</strong></td>
    <td style="padding: 8px; border-bottom: 1px solid #eee; text-align: right;">${assignment.amount:.2f}</td>
</tr>
<tr>
    <td colspan="2" style="padding: 4px 8px 12px; color: #666; font-size: 13px;">{items_list}</td>
</tr>
"""

    # Build YNAB link section if URL provided
    ynab_link_html = ""
    if ynab_url:
        ynab_link_html = f'<a href="{ynab_url}" style="color: #0066cc; text-decoration: none;">View in YNAB →</a>'

    return f"""
<html>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px;">
<h2>✅ Amazon Order Categorized</h2>

<p><strong>Order:</strong> #{order_id}</p>
<p><strong>Total:</strong> ${order_total:.2f}</p>

<h3>Categorization:</h3>
<table style="width: 100%; border-collapse: collapse;">
{categories_html}
</table>

<p style="margin-top: 20px; padding: 12px; background: #e8f5e9; border-radius: 4px;">
✓ Applied to YNAB {ynab_link_html}
</p>

<p style="color: #888; font-size: 12px; margin-top: 20px;">
Sent by YNAB Amazon Itemizer
</p>
</body>
</html>
"""


def create_reply_message(
    to: str,
    subject: str,
    html_body: str,
    in_reply_to: Optional[str] = None,
    references: Optional[str] = None,
    cc: Optional[str] = None,
) -> dict:
    """
    Create a Gmail API message object for sending.

    Args:
        to: Recipient email address
        subject: Email subject
        html_body: HTML body content
        in_reply_to: Message-ID of email being replied to
        references: References header for threading
        cc: CC email address(es)

    Returns:
        Gmail API message object
    """
    message = MIMEMultipart("alternative")
    message["to"] = to
    message["subject"] = subject

    if cc:
        message["cc"] = cc

    if in_reply_to:
        message["In-Reply-To"] = in_reply_to
        message["References"] = references or in_reply_to

    # Add HTML part
    html_part = MIMEText(html_body, "html")
    message.attach(html_part)

    # Encode for Gmail API
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
    return {"raw": raw}


def send_summary_email(
    gmail_service,
    to: List[str],  # Changed to list of recipients
    order_id: str,
    order_total: Decimal,
    result: Optional[CategorizationResult] = None,
    matched: bool = True,
    error: Optional[str] = None,
    in_reply_to: Optional[str] = None,
    original_subject: Optional[str] = None,
    thread_id: Optional[str] = None,
    ynab_url: Optional[str] = None,
) -> bool:
    """
    Send a summary email via Gmail API.

    Args:
        gmail_service: Authenticated Gmail API service
        to: List of recipient email addresses
        order_id: Amazon order ID
        order_total: Order total amount
        result: Categorization result (if categorized)
        matched: Whether YNAB transaction was found
        error: Error message (if any)
        in_reply_to: Message-ID to reply to (for threading)
        original_subject: Original email subject (for reply subject)
        thread_id: Gmail thread ID (for threading replies)
        ynab_url: Direct link to transaction in YNAB

    Returns:
        True if sent successfully
    """
    # Handle both string and list for backwards compatibility
    if isinstance(to, str):
        recipients = [to]
    else:
        recipients = [r for r in to if r]  # Filter out empty strings

    if not recipients:
        print("No recipients specified, skipping email")
        return False

    # Format the email body
    html_body = format_summary_email(
        order_id=order_id,
        order_total=order_total,
        result=result,
        matched=matched,
        error=error,
        ynab_url=ynab_url,
    )

    # Build subject - always include order ID for correction replies to find
    if original_subject:
        # Append order ID if not already in subject
        if order_id not in original_subject:
            subject = f"Re: {original_subject} [Order {order_id}]"
        else:
            subject = f"Re: {original_subject}"
    else:
        status = "✅ Categorized" if result else ("⏳ Pending" if not matched else "📦 Received")
        subject = f"{status} - Amazon Order #{order_id}"

    # Create message with all recipients
    all_recipients = ", ".join(recipients)
    message = create_reply_message(
        to=all_recipients,
        subject=subject,
        html_body=html_body,
        in_reply_to=in_reply_to,
    )

    # Add thread ID for proper Gmail threading
    if thread_id:
        message["threadId"] = thread_id

    try:
        gmail_service.users().messages().send(
            userId="me",
            body=message
        ).execute()
        print(f"Sent summary email to: {all_recipients}")
        return True
    except Exception as e:
        print(f"Error sending email: {e}")
        return False


def format_clarification_email(options: List[Dict], pending_category: str) -> str:
    """Format a terse clarification email when item is ambiguous.

    Args:
        options: List of {"num": 1, "item": "...", "amount": "$X.XX"}
        pending_category: Category that will be applied

    Returns:
        HTML email body
    """
    options_html = ""
    for opt in options:
        options_html += f'<div style="padding: 4px 0;">{opt["num"]}. {opt["item"]} ({opt["amount"]})</div>\n'

    return f"""
<html>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px;">
<p><strong>Which one?</strong> → {pending_category}</p>

<div style="padding: 8px 0; font-size: 14px;">
{options_html}
</div>

<p style="color: #666; font-size: 13px;">Reply: 1, 2, or "both"</p>
</body>
</html>
"""


def send_clarification_email(
    gmail_service,
    to: List[str],
    order_id: str,
    options: List[Dict],
    pending_category: str,
    in_reply_to: Optional[str] = None,
    original_subject: Optional[str] = None,
    thread_id: Optional[str] = None,
) -> bool:
    """Send a clarification email when item is ambiguous.

    Args:
        gmail_service: Authenticated Gmail API service
        to: List of recipient email addresses
        order_id: Amazon order ID
        options: List of {"num": 1, "item": "...", "amount": "$X.XX"}
        pending_category: Category that will be applied
        in_reply_to: Message-ID to reply to
        original_subject: Original email subject
        thread_id: Gmail thread ID

    Returns:
        True if sent successfully
    """
    recipients = [r for r in to if r] if isinstance(to, list) else [to]
    if not recipients:
        return False

    html_body = format_clarification_email(options, pending_category)

    subject = f"Re: {original_subject}" if original_subject else f"Clarification needed - Order #{order_id}"

    all_recipients = ", ".join(recipients)
    message = create_reply_message(
        to=all_recipients,
        subject=subject,
        html_body=html_body,
        in_reply_to=in_reply_to,
    )

    if thread_id:
        message["threadId"] = thread_id

    try:
        gmail_service.users().messages().send(userId="me", body=message).execute()
        print(f"Sent clarification email to: {all_recipients}")
        return True
    except Exception as e:
        print(f"Error sending clarification email: {e}")
        return False


def format_correction_confirmation_email(
    order_id: str,
    transaction: YNABTransaction,
    ynab_url: Optional[str] = None,
    changes: Optional[List[Dict]] = None,
) -> str:
    """Format a confirmation email showing the full updated categorization.

    Args:
        order_id: Amazon order ID
        transaction: Updated YNABTransaction with subtransactions
        ynab_url: Link to YNAB account
        changes: List of {"item": "...", "new_category": "..."} for marking updated items

    Returns:
        HTML email body
    """
    # Build set of changed items (lowercased) for marking
    changed_items = set()
    if changes:
        for change in changes:
            changed_items.add(change.get("item", "").lower())

    # Build categorization table from subtransactions
    categories_html = ""
    for sub in transaction.subtransactions:
        memo = sub.get("memo", "Unknown item")
        cat_name = sub.get("category_name", "Uncategorized")
        amount = sub.get("amount", 0)
        # Convert milliunits to dollars
        if isinstance(amount, int):
            amount_dollars = abs(amount) / 1000
        else:
            amount_dollars = abs(float(amount))

        # Check if this item was changed
        is_changed = any(item in memo.lower() for item in changed_items)
        updated_marker = ' <span style="color: #4CAF50; font-size: 11px;">(Updated)</span>' if is_changed else ""

        categories_html += f"""
<tr>
    <td style="padding: 8px; border-bottom: 1px solid #eee;">{memo}</td>
    <td style="padding: 8px; border-bottom: 1px solid #eee;"><strong>{cat_name}</strong>{updated_marker}</td>
    <td style="padding: 8px; border-bottom: 1px solid #eee; text-align: right;">${amount_dollars:.2f}</td>
</tr>
"""

    ynab_link_html = ""
    if ynab_url:
        ynab_link_html = f'<a href="{ynab_url}" style="color: #0066cc; text-decoration: none;">View in YNAB →</a>'

    return f"""
<html>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px;">
<h2>✅ Categorization Updated</h2>

<p><strong>Order:</strong> #{order_id}</p>

<h3>Current Categorization:</h3>
<table style="width: 100%; border-collapse: collapse;">
<tr style="background: #f5f5f5;">
    <th style="padding: 8px; text-align: left;">Item</th>
    <th style="padding: 8px; text-align: left;">Category</th>
    <th style="padding: 8px; text-align: right;">Amount</th>
</tr>
{categories_html}
</table>

<p style="margin-top: 20px; padding: 12px; background: #e8f5e9; border-radius: 4px;">
✓ Updated in YNAB {ynab_link_html}
</p>

<p style="color: #888; font-size: 12px; margin-top: 20px;">
Reply to make more changes.
</p>
</body>
</html>
"""


def send_correction_confirmation_email(
    gmail_service,
    to: List[str],
    order_id: str,
    transaction: YNABTransaction,
    in_reply_to: Optional[str] = None,
    original_subject: Optional[str] = None,
    thread_id: Optional[str] = None,
    ynab_url: Optional[str] = None,
    cc: Optional[List[str]] = None,
    changes: Optional[List[Dict]] = None,
) -> bool:
    """Send a confirmation email showing the full updated categorization.

    Args:
        gmail_service: Authenticated Gmail API service
        to: List of recipient email addresses
        order_id: Amazon order ID
        transaction: Updated YNABTransaction with subtransactions
        in_reply_to: Message-ID to reply to
        original_subject: Original email subject
        thread_id: Gmail thread ID
        ynab_url: Link to YNAB account
        cc: List of CC email addresses
        changes: List of changes for marking updated items

    Returns:
        True if sent successfully
    """
    recipients = [r for r in to if r] if isinstance(to, list) else [to]
    if not recipients:
        return False

    html_body = format_correction_confirmation_email(order_id, transaction, ynab_url, changes)

    subject = f"Re: {original_subject}" if original_subject else f"✅ Updated - Order #{order_id}"

    all_recipients = ", ".join(recipients)
    cc_str = ", ".join(cc) if cc else None
    message = create_reply_message(
        to=all_recipients,
        subject=subject,
        html_body=html_body,
        in_reply_to=in_reply_to,
        cc=cc_str,
    )

    if thread_id:
        message["threadId"] = thread_id

    try:
        gmail_service.users().messages().send(userId="me", body=message).execute()
        print(f"Sent correction confirmation email to: {all_recipients}")
        return True
    except Exception as e:
        print(f"Error sending correction confirmation email: {e}")
        return False
