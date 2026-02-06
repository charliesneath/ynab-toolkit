# Transaction Processing Details

See [README.md](README.md) for the main workflow. This document covers additional details about the processing output.

## Output CSV Columns

| Column | Description |
|--------|-------------|
| Date | Transaction date |
| Order ID | Amazon order ID |
| Amount | Transaction amount |
| Type | Purchase or Refund |
| Status | OK or NEEDS ATTENTION |
| Category | Primary budget category |
| Category Group | YNAB category group |
| Payee | Amazon.com, Whole Foods, etc. |
| Items | Item names from order |
| Notes | What's needed (e.g., "need order history export") |
| Last Updated | When this transaction was last processed |

## Transaction Status

| Status | Flag | Meaning |
|--------|------|---------|
| OK | Yellow | Successfully matched and categorized |
| NEEDS ATTENTION | Blue | Requires manual action |

### NEEDS ATTENTION Reasons

- **Order not found** - Order ID not in your Amazon order history export. Usually means it's from another household member's Amazon account.
- **No shipment match** - Items found but charge amount doesn't match any shipment (partial shipment, price adjustment, etc.)
- **Needs itemization** - Order found but no item details available

## Grocery Order Handling

Grocery orders (Whole Foods, Amazon Fresh) are handled differently from regular Amazon orders:

| Field | Regular Orders | Grocery Orders |
|-------|----------------|----------------|
| `category` | Not set (uses splits) | "Groceries" |
| `splits` | Per-item with categories | Empty |
| `grocery_items` | Not set | Full item details |
| `is_grocery` | `false` | `true` |

**Detection:** Grocery orders are identified by the `Shipping Option` field in Amazon order history. Orders with `scheduled-houdini` or `scheduled-one-houdini` shipping are marked as grocery.

**Analysis:** The `grocery_items` field in the JSON cache contains full item details (name, amount, quantity) for separate grocery spending analysis, even though these items aren't synced as splits to YNAB.

## Import ID Format

Transactions use a unique import_id to prevent duplicates:
```
AMZ2:{order_id}:{amount_cents}:{direction}
```
- `order_id` - Amazon order ID
- `amount_cents` - Amount in cents (absolute value)
- `direction` - P (purchase) or R (refund)

Example: `AMZ2:112-1234567-8901234:4247:P`

## Re-processing

The processor caches results in JSON. To force re-processing:
1. Delete the corresponding `.json` file in `data/processed/{account}/`
2. Run `process_transactions.py` again

Already-synced transactions are tracked in the JSON and won't be re-uploaded.
