"""Parse Amazon order confirmation emails to extract order details."""

import re
import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import List, Optional

import anthropic

from config import CLAUDE_MODEL
from email_fetcher import RawEmail


@dataclass
class ParsedItem:
    """An item from an Amazon order email."""
    title: str
    price: Optional[Decimal]
    quantity: int = 1


@dataclass
class ParsedOrder:
    """Parsed Amazon order from email."""
    order_id: str
    order_date: datetime
    total: Decimal
    items: List[ParsedItem]
    email_uid: str
    email_subject: str

    def to_json(self) -> str:
        """Convert items to JSON for storage."""
        items_data = [
            {"title": i.title, "price": str(i.price) if i.price else None, "quantity": i.quantity}
            for i in self.items
        ]
        return json.dumps(items_data)

    @staticmethod
    def items_from_json(json_str: str) -> List[ParsedItem]:
        """Recreate items from JSON."""
        items_data = json.loads(json_str)
        return [
            ParsedItem(
                title=i["title"],
                price=Decimal(i["price"]) if i["price"] else None,
                quantity=i["quantity"]
            )
            for i in items_data
        ]


PARSE_PROMPT = """Extract order information from this Amazon email. Return a JSON object with:
- order_id: The Amazon order number (format: XXX-XXXXXXX-XXXXXXX)
- total: The order total as a number (just the number, no $ sign)
- items: Array of items that were ACTUALLY ORDERED, each with:
  - title: Product name (be concise, ~50 chars max)
  - price: Item price as a number (if shown, otherwise null)
  - quantity: Number ordered (default 1)

IMPORTANT: Only include items that were actually purchased in this order.
IGNORE any of the following sections - these are NOT part of the order:
- "Customers who bought this also bought"
- "Recommended for you"
- "Frequently bought together"
- "Sponsored products"
- "More items to explore"
- Any advertisements or product suggestions

If this is not an Amazon order email or you cannot extract the information, return {{"error": "reason"}}.

Return ONLY valid JSON, no other text.

Email content:
"""


class AmazonEmailParser:
    """Parse Amazon order confirmation emails using Claude."""

    def __init__(self, client: Optional[anthropic.Anthropic] = None):
        """Initialize parser with optional Anthropic client."""
        self.client = client

    def _strip_html(self, html: str) -> str:
        """Convert HTML to clean plain text, removing noise."""
        # Remove style and script tags
        html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
        # Remove hidden/tracking elements
        html = re.sub(r'<img[^>]*>', '', html, flags=re.IGNORECASE)
        html = re.sub(r'display:\s*none[^;]*;?', '', html, flags=re.IGNORECASE)

        # Replace common tags with whitespace
        html = re.sub(r'<br\s*/?>', '\n', html, flags=re.IGNORECASE)
        html = re.sub(r'</p>', '\n', html, flags=re.IGNORECASE)
        html = re.sub(r'</div>', '\n', html, flags=re.IGNORECASE)
        html = re.sub(r'</tr>', '\n', html, flags=re.IGNORECASE)
        html = re.sub(r'</td>', ' ', html, flags=re.IGNORECASE)

        # Remove all other tags
        html = re.sub(r'<[^>]+>', '', html)

        # Decode entities
        html = html.replace('&nbsp;', ' ')
        html = html.replace('&amp;', '&')
        html = html.replace('&lt;', '<')
        html = html.replace('&gt;', '>')
        html = html.replace('&quot;', '"')
        html = html.replace('&#39;', "'")
        html = html.replace('&#x27;', "'")

        # Remove invisible unicode chars and excessive whitespace
        html = re.sub(r'[\u200b-\u200f\u2028-\u202f\u00ad\u034f\u115f\u1160\u17b4\u17b5\ufeff]+', '', html)
        html = re.sub(r'͏', '', html)  # Remove combining grapheme joiner
        html = re.sub(r'[ \t]+', ' ', html)
        html = re.sub(r'\n[ \t]+', '\n', html)
        html = re.sub(r'\n{3,}', '\n\n', html)

        # Remove common noise phrases
        noise = [
            r'If you need more information.*?contact.*?\d+',
            r'By placing your order.*?Conditions of Use',
            r'©\d{4} Amazon\.com.*?affiliates',
            r'You can view your order.*?Amazon app',
        ]
        for pattern in noise:
            html = re.sub(pattern, '', html, flags=re.IGNORECASE | re.DOTALL)

        return html.strip()

    def _parse_with_claude(self, content: str, subject: str) -> Optional[dict]:
        """Use Claude to parse email content."""
        if not self.client:
            return None

        # Truncate content aggressively to reduce tokens (keep first 3000 chars)
        if len(content) > 3000:
            content = content[:3000] + "\n...[truncated]"

        prompt = PARSE_PROMPT + f"Subject: {subject}\n\n{content}"

        try:
            response = self.client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=512,  # Reduced - JSON response is small
                messages=[{"role": "user", "content": prompt}]
            )

            result_text = response.content[0].text.strip()

            # Extract JSON from response (handle markdown code blocks)
            if "```" in result_text:
                json_match = re.search(r'```(?:json)?\s*(.*?)```', result_text, re.DOTALL)
                if json_match:
                    result_text = json_match.group(1).strip()

            return json.loads(result_text)
        except anthropic.BadRequestError as e:
            error_str = str(e)
            if "credit balance" in error_str.lower() or "quota" in error_str.lower():
                print(f"ANTHROPIC QUOTA EXHAUSTED: {e}")
                return {"error": "quota_exhausted", "message": str(e)}
            print(f"Claude API error: {e}")
            return {"error": "api_error", "message": str(e)}
        except anthropic.RateLimitError as e:
            print(f"ANTHROPIC RATE LIMIT: {e}")
            return {"error": "rate_limited", "message": str(e)}
        except Exception as e:
            print(f"Claude parsing error: {e}")
            return None

    def _fallback_parse(self, text: str, subject: str) -> Optional[dict]:
        """Regex fallback if Claude is unavailable."""
        # Extract order ID
        order_id = None
        for pattern in [r'(\d{3}-\d{7}-\d{7})']:
            match = re.search(pattern, text)
            if match:
                order_id = match.group(1)
                break

        if not order_id:
            return None

        # Extract total
        total = None
        for pattern in [r'Grand Total[:\s]*\$?([\d,]+\.?\d*)', r'Order Total[:\s]*\$?([\d,]+\.?\d*)']:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    total = float(match.group(1).replace(',', ''))
                    break
                except ValueError:
                    pass

        if not total:
            return None

        # Try to extract item from subject
        item_name = f"Amazon Order {order_id}"
        subject_match = re.search(r'Ordered:\s*["\']?(.+?)["\']?\s*(?:\.\.\.|$)', subject)
        if subject_match:
            item_name = subject_match.group(1).strip()

        return {
            "order_id": order_id,
            "total": total,
            "items": [{"title": item_name, "price": total, "quantity": 1}]
        }

    def parse_email(self, email: RawEmail) -> Optional[ParsedOrder]:
        """
        Parse an Amazon order email using Claude.

        Args:
            email: RawEmail object from email_fetcher

        Returns:
            ParsedOrder if successfully parsed, None otherwise
        """
        content = email.html_body or email.text_body
        if not content:
            return None

        text_content = self._strip_html(content)

        # Try Claude first, fall back to regex
        parsed = self._parse_with_claude(text_content, email.subject)

        # Check for critical API errors that should bubble up
        if parsed and parsed.get("error") in ("quota_exhausted", "rate_limited"):
            print(f"CRITICAL API ERROR: {parsed}")
            # Return a special marker so caller knows it's an API issue
            raise Exception(f"ANTHROPIC_ERROR:{parsed['error']}:{parsed.get('message', '')}")

        if not parsed or "error" in parsed:
            print(f"Claude parse failed: {parsed}, trying fallback")
            parsed = self._fallback_parse(text_content, email.subject)

        if not parsed:
            print(f"All parsing failed for: {email.subject[:60]}")
            print(f"Content preview: {text_content[:500]}")
            return None

        # Build ParsedOrder
        try:
            items = [
                ParsedItem(
                    title=item.get("title", "Unknown Item")[:200],
                    price=Decimal(str(item["price"])) if item.get("price") else None,
                    quantity=item.get("quantity", 1)
                )
                for item in parsed.get("items", [])
            ]

            total = Decimal(str(parsed["total"]))

            # Distribute total if items don't have prices
            items_without_price = [i for i in items if i.price is None]
            if items_without_price:
                price_per_item = total / len(items_without_price)
                for item in items_without_price:
                    item.price = price_per_item

            return ParsedOrder(
                order_id=parsed["order_id"],
                order_date=email.date,
                total=total,
                items=items if items else [ParsedItem(title=f"Amazon Order", price=total, quantity=1)],
                email_uid=email.uid,
                email_subject=email.subject
            )
        except (KeyError, ValueError, TypeError) as e:
            print(f"Error building ParsedOrder: {e}")
            return None


def parse_amazon_emails(
    emails: List[RawEmail],
    client: Optional[anthropic.Anthropic] = None
) -> List[ParsedOrder]:
    """Parse a list of Amazon emails into orders."""
    parser = AmazonEmailParser(client=client)
    orders = []
    seen_order_ids = set()

    for email in emails:
        try:
            order = parser.parse_email(email)
            if order and order.order_id not in seen_order_ids:
                orders.append(order)
                seen_order_ids.add(order.order_id)
        except Exception as e:
            print(f"Error parsing email '{email.subject}': {e}")

    return orders
