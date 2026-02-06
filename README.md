# YNAB Amazon Itemizer

Automatically categorize and itemize Amazon orders in [YNAB](https://www.ynab.com/) using AI.

## What is YNAB?

[YNAB](https://www.ynab.com/) (You Need A Budget) is a popular budgeting app that helps you assign every dollar a job. It connects to your bank accounts and imports transactions, which you then categorize into budget categories like Groceries, Entertainment, or Shopping. This gives you visibility into where your money goes and helps you make intentional spending decisions.

## The Problem

YNAB auto-categorizes transactions based on the payee, using the category from your last transaction with that payee. This doesn't always work for Amazon—purchases span multiple categories (groceries, electronics, clothing, household items) all under the same "AMAZON.COM" payee. Multi-item orders should also be split across categories.

## The Solution

This tool automatically:
- Matches Amazon charges to your order history
- Identifies individual items in each order
- Uses Claude AI to categorize items into your YNAB budget categories
- Creates split transactions for multi-item orders

Supports two approaches:

- **Automated Solution** - Forward Amazon order emails for real-time processing via Google Cloud
- **Backfill Solution** - Batch process historical transactions from PDF statements and Amazon order history

## Features

- **AI Categorization** - Claude categorizes items into your YNAB categories
- **Split Transactions** - Multi-item orders become itemized splits
- **PDF Statement Parsing** - Convert Chase PDF statements to YNAB CSV format
- **Amazon Order Matching** - Match charges to your Amazon order history
- **Transaction Comparison** - Reconcile bank statements against YNAB

---

## Automated Solution (Email-Based)

Forward Amazon order confirmation emails to a dedicated inbox for real-time categorization. You can set up a Gmail filter to auto-forward Amazon order emails, making this completely hands-off.

### How It Works

```
Amazon order email → Auto-forward → Gmail inbox → Cloud Function → YNAB updated
```

1. Amazon order email arrives (auto-forwarded via Gmail filter)
2. Cloud Function automatically processes it via Gmail push notifications
3. Claude AI parses the order and categorizes items
4. YNAB transaction is created (or matched to existing) with split categories
5. Reply email is sent back with the categorization summary

### Setup

#### Prerequisites
- Google Cloud project with these APIs enabled:
  - Gmail API
  - Cloud Functions
  - Pub/Sub
  - Secret Manager
  - Cloud Scheduler
- Gmail account for receipts inbox
- OAuth 2.0 credentials (Desktop app) from Google Cloud Console

#### 1. Create Pub/Sub Topic
```bash
gcloud pubsub topics create amazon-receipts --project YOUR_PROJECT_ID
```

#### 2. Store Secrets in Secret Manager
```bash
# YNAB API token
echo -n "your-ynab-token" | gcloud secrets create ynab-token --data-file=- --project YOUR_PROJECT_ID

# Anthropic API key
echo -n "your-anthropic-key" | gcloud secrets create anthropic-api-key --data-file=- --project YOUR_PROJECT_ID

# YNAB budget name
echo -n "Your Budget Name" | gcloud secrets create ynab-budget-name --data-file=- --project YOUR_PROJECT_ID

# Gmail OAuth token (after running setup_gmail_push.py locally)
cat data/gmail_token.json | gcloud secrets create gmail-oauth-token --data-file=- --project YOUR_PROJECT_ID
```

#### 3. Set Up Gmail OAuth Token
```bash
# Download OAuth credentials from Google Cloud Console to data/gmail_credentials.json
# Then run:
python setup_gmail_push.py --topic projects/YOUR_PROJECT_ID/topics/amazon-receipts
```
This opens a browser for OAuth authentication and creates `data/gmail_token.json`.

#### 4. Grant Pub/Sub Permissions
Gmail needs permission to publish to your Pub/Sub topic:
```bash
gcloud pubsub topics add-iam-policy-binding amazon-receipts \
  --member="serviceAccount:gmail-api-push@system.gserviceaccount.com" \
  --role="roles/pubsub.publisher" \
  --project YOUR_PROJECT_ID
```

**Key files:**
- `main.py` - Cloud Function entry point
- `email_parser.py` - Amazon email parsing
- `email_fetcher.py` - Gmail API integration
- `email_sender.py` - Reply email handling
- `setup_gmail_push.py` - Gmail watch setup script

### Deployment

Deploy the Cloud Functions to Google Cloud:

```bash
# Main email processing function (Pub/Sub triggered)
gcloud functions deploy process_gmail_push \
  --gen2 \
  --runtime python312 \
  --trigger-topic amazon-receipts \
  --source . \
  --entry-point process_gmail_push \
  --region us-central1 \
  --timeout 120 \
  --memory 256MB \
  --set-env-vars GCP_PROJECT_ID=YOUR_PROJECT_ID

# Gmail watch renewal function (HTTP triggered, called by Cloud Scheduler)
gcloud functions deploy renew_gmail_watch \
  --gen2 \
  --runtime python312 \
  --trigger-http \
  --source . \
  --entry-point renew_gmail_watch \
  --region us-central1 \
  --timeout 60 \
  --memory 256MB \
  --allow-unauthenticated \
  --set-env-vars GCP_PROJECT_ID=YOUR_PROJECT_ID
```

### Gmail Watch Auto-Renewal

Gmail watches expire after 7 days. A Cloud Scheduler job automatically renews the watch every 6 days:

```bash
# Enable Cloud Scheduler API (one-time)
gcloud services enable cloudscheduler.googleapis.com --project YOUR_PROJECT_ID

# Create the scheduler job
gcloud scheduler jobs create http renew-gmail-watch \
  --project YOUR_PROJECT_ID \
  --location us-central1 \
  --schedule "0 0 */6 * *" \
  --uri "https://us-central1-YOUR_PROJECT_ID.cloudfunctions.net/renew_gmail_watch" \
  --http-method GET \
  --description "Renew Gmail watch every 6 days to prevent expiration"
```

To manually renew the watch:
```bash
curl https://us-central1-YOUR_PROJECT_ID.cloudfunctions.net/renew_gmail_watch
```

### Debugging

View logs to debug issues:

```bash
gcloud functions logs read process_gmail_push --limit 20 --region us-central1
```

### Troubleshooting

**`ModuleNotFoundError: No module named 'imp'`**
Your gcloud SDK is outdated. Update with:
```bash
brew upgrade google-cloud-sdk
```

**`invalid_grant: Token has been expired or revoked`**
The Gmail OAuth token in Secret Manager is expired. Refresh it:
```bash
# Delete old local token and re-authenticate
rm data/gmail_token.json
python setup_gmail_push.py --topic projects/YOUR_PROJECT_ID/topics/amazon-receipts

# Update Secret Manager
cat data/gmail_token.json | gcloud secrets versions add gmail-oauth-token --data-file=- --project YOUR_PROJECT_ID

# Redeploy to pick up new token
gcloud functions deploy process_gmail_push ... (see Deployment section)
```

**`Permission denied on resource project None`**
The `GCP_PROJECT_ID` environment variable is not set. Redeploy with:
```bash
--set-env-vars GCP_PROJECT_ID=YOUR_PROJECT_ID
```

**Emails not triggering the function**
The Gmail watch may have expired. Check and renew:
```bash
# Check watch status
curl https://us-central1-YOUR_PROJECT_ID.cloudfunctions.net/renew_gmail_watch

# Or run locally
python setup_gmail_push.py --topic projects/YOUR_PROJECT_ID/topics/amazon-receipts
```

**Order skipped but transaction was deleted**
YNAB API may cache deleted transactions briefly. Wait a few minutes and forward the email again.

---

## Backfill Solution (Batch Processing)

Process historical transactions from PDF bank statements against Amazon order history. Use this to categorize past transactions or catch up on periods before the automated solution was set up.

### Quick Start

```bash
# 1. Install dependencies
pip install pdfplumber anthropic python-dotenv requests

# 2. Configure environment
cp .env.example .env
# Edit .env with your YNAB_TOKEN, BUDGET_NAME, ACCOUNT_NAME, ANTHROPIC_API_KEY

# 3. Parse PDF statements to CSV
python bank_to_ynab.py amazon-card data/amazon/statements/*.pdf -o data/amazon/ynab_amazon_2025.csv

# 4. Match orders and categorize
python process_transactions.py data/amazon/ynab_amazon_2025.csv

# 5. Sync to YNAB
python sync_to_ynab.py all
```

### Workflow

```
PDF Statements → CSV → Match Amazon Orders → AI Categorize → Sync to YNAB
       ↓                      ↓                    ↓              ↓
 bank_to_ynab.py    process_transactions.py    (included)   sync_to_ynab.py
```

### Tools

#### 1. PDF Statement Converter (`bank_to_ynab.py`)

Convert bank PDF statements to YNAB-compatible CSV format.

```bash
# Chase Amazon credit card
python bank_to_ynab.py amazon-card data/amazon/statements/*.pdf -o ynab_amazon.csv

# Chase checking account
python bank_to_ynab.py chase-checking data/checking/*.pdf -o ynab_checking.csv --year 2024

# Generic CSV conversion
python bank_to_ynab.py csv data/export.csv -o ynab_import.csv
```

**Options:**
- `--year YYYY` - Filter to specific year
- `--date-format` - Date format for CSV files (default: %m/%d/%Y)

#### 2. Transaction Processor (`process_transactions.py`)

Match Amazon charges to order history and categorize with Claude AI.

```bash
# Process a year of transactions (synchronous, immediate results)
python process_transactions.py data/amazon/ynab_amazon_2025.csv

# Use Batches API (50% cheaper, async - up to 24 hours)
python process_transactions.py data/amazon/ynab_amazon_2025.csv --batch

# Check batch status
python process_transactions.py --batch-status

# Retrieve completed batch results
python process_transactions.py --batch-results BATCH_ID
```

**Batch Processing:**
The `--batch` flag uses Anthropic's Batches API which is 50% cheaper but processes asynchronously (up to 24 hours). Ideal for large backfill operations where immediate results aren't needed.

**Output:**
- `data/processed/{account}/YYYY-all.json` - Full transaction data with splits
- `data/processed/{account}/YYYY-all.csv` - Human-readable summary for review

**Prerequisites:**
- Amazon Order History Export in `data/amazon/order history/`
  (Amazon > Account > Download Your Data > Your Orders)
  Note: Amazon data requests can take a few days to process.

#### 3. YNAB Sync (`sync_to_ynab.py`)

Upload processed transactions to YNAB with duplicate detection.

```bash
# List available cache files
python sync_to_ynab.py --list

# Preview what will be created
python sync_to_ynab.py 2025-all.json --dry-run

# Sync specific file
python sync_to_ynab.py 2025-all.json

# Sync all processed files
python sync_to_ynab.py all
```

#### 4. Credit Card Payments (`extract_checking_payments.py`)

Match credit card payments between checking and Amazon card accounts for proper YNAB transfers.

**Problem:** When you pay your Amazon card from checking, YNAB sees:
- Checking: Outflow to "Payment To Chase Card Ending IN XXXX"
- Amazon Card: Inflow from "Payment Thank You"

These need to be matched and converted to transfers.

**Workflow:**

```bash
# 1. Convert checking statements to CSV
python bank_to_ynab.py chase-checking data/checking/statements/*.pdf -o data/checking_all.csv

# 2. Run the matching script
python extract_checking_payments.py
```

**Output:**
- `data/checking_amazon_transfers.csv` - Import to checking account (transfers out)
- `data/amazon_card_payments.csv` - Import to Amazon card account (transfers in)

**Matching Logic:**
- Matches by exact amount within 3 days
- Unmatched Amazon payments marked "NEEDS REVIEW" (paid from different account)
- Unmatched checking payments listed for investigation

**Import to YNAB:**
1. Import `checking_amazon_transfers.csv` to your Checking account
2. Import `amazon_card_payments.csv` to your Amazon Card account
3. YNAB will auto-match the transfers

#### 5. Transaction Comparison (`compare.py`)

Compare bank statements against YNAB to find discrepancies.

```bash
python compare.py --chase data/chase-export.csv
```

### Backfill Workflow

1. Download PDF statements from Chase for the period you want to backfill
2. Export Amazon order history (Amazon > Account > Download Your Data > Your Orders)
3. Convert PDFs: `python bank_to_ynab.py amazon-card data/amazon/statements/*.pdf -o data/amazon/ynab_amazon_2025.csv --year 2025`
4. Process: `python process_transactions.py data/amazon/ynab_amazon_2025.csv`
5. Review CSV for "NEEDS ATTENTION" items
6. Add other household members' order history if needed, re-process
7. Sync: `python sync_to_ynab.py all`
8. Review and approve in YNAB

---

## Configuration

### Category Descriptions (`data/category_descriptions.csv`)

Customize AI categorization with hints and exclusions:

| Column | Description |
|--------|-------------|
| group | YNAB category group name |
| category | YNAB category name |
| description | Hints for AI (e.g., "cleaning sprays, sponges, dish soap") |
| exclude | Set to `yes` to hide from AI prompts |

Example:
```csv
group,category,description,exclude
Shopping,Kitchen & Cleaning Supplies,"dish soap, dishwasher pods, sponges",
Savings,Emergency Fund,,yes
Travel,Vacation 2025,,yes
```

### Environment Variables

Create `.env` file:

```env
YNAB_TOKEN=your_ynab_personal_access_token
BUDGET_NAME=Your Budget Name
ACCOUNT_NAME=Chase Amazon
ANTHROPIC_API_KEY=your_anthropic_key
```

**API Keys:**
- YNAB Personal Access Token: [YNAB Developer Settings](https://app.ynab.com/settings/developer)
- Anthropic API Key: [Anthropic Console](https://console.anthropic.com/)

## Transaction Flags

- **Yellow flag** - Successfully itemized and categorized
- **Blue flag** - Needs manual attention (order not found or no match)

## Special Transaction Handling

### Grocery Orders (Whole Foods / Amazon Fresh)

Grocery orders are detected automatically via the shipping option in your Amazon order history (`scheduled-houdini` for grocery deliveries). These transactions are:

- **Categorized as "Groceries"** - Single category, no item-by-item splits
- **Not itemized in YNAB** - Grocery items don't need per-item budget tracking
- **Items saved for analysis** - Full item details stored in `grocery_items` field in the JSON cache for separate analysis

This keeps YNAB transactions clean while preserving item data if you want to analyze grocery spending separately.

### Delivery Tips

Amazon Fresh and Whole Foods delivery tips are automatically detected via the "Amazon Tips" payee and categorized as "Delivery Fee" without itemization. Tips appear as separate transactions with the same order ID as the main grocery order.

### Quantity Display

When multiple quantities of the same item are purchased, the memo shows a quantity prefix (e.g., "2 x Paper Towels" instead of listing the item twice). This keeps split transactions readable.

### Category Exclusions

Categories marked as `exclude=yes` in `data/category_descriptions.csv` are hidden from AI categorization prompts. Use this for categories that shouldn't be auto-assigned (e.g., savings goals, specific trip budgets).

## Categories

Items are categorized into:
- Shopping, Electronics, Home & Garden, Clothing
- Health & Personal Care, Kids, Pets
- Entertainment, Office, Sports & Outdoors, Automotive
- Groceries (Produce, Dairy, Meat, etc.)

## File Structure

```
ynab-amazon-itemize/
├── main.py                   # Cloud Function (automated solution)
├── email_parser.py           # Amazon email parsing with Claude
├── email_fetcher.py          # Gmail API integration
├── email_sender.py           # Reply email handling
├── categorizer.py            # AI item categorization
├── amazon_parser.py          # Amazon order data structures
├── utils.py                  # Shared utilities and category cache
├── bank_to_ynab.py           # PDF/CSV converter (backfill solution)
├── process_transactions.py   # Order matching & categorization
├── sync_to_ynab.py           # Upload to YNAB
├── compare.py                # Transaction reconciliation
│
├── # Read/Write Separation
├── ynab_client.py            # YNAB API client (read-only)
├── ynab_writer.py            # YNAB API writes (create/update/delete)
├── file_writer.py            # File system writes (cache, CSV reports)
├── api_writer.py             # External API writes (Firestore, Gmail)
│
├── converters/               # Bank statement parsers
│   ├── chase_amazon.py       # Chase Amazon card PDF parser
│   ├── chase_checking.py     # Chase checking PDF parser
│   └── csv_import.py         # Generic CSV converter
├── .claude/
│   └── hooks/
│       ├── auto_approve_reads.py    # Auto-approve read operations
│       └── destructive_patterns.py  # Patterns that require approval
├── data/
│   ├── amazon/
│   │   ├── statements/       # PDF statements
│   │   └── order history/    # Amazon order history export
│   └── processed/            # Cached transaction data
│       └── {account}/
│           ├── YYYY-all.json # Transaction data with splits
│           ├── YYYY-all.csv  # Human-readable summary
│           ├── category_cache.json  # Persistent category cache
│           └── pending_batches.json # Async batch job tracking
└── .env                      # Configuration
```

## How It Works (Technical Details)

### Transaction Processing Pipeline

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Bank Statement │────▶│  Order Matching │────▶│  Categorization │
│    (CSV/PDF)    │     │   (by Order ID) │     │    (Claude AI)  │
└─────────────────┘     └─────────────────┘     └─────────────────┘
                                                         │
                        ┌─────────────────┐              ▼
                        │    YNAB Sync    │◀────┌─────────────────┐
                        │  (Batch Create) │     │  Category Cache │
                        └─────────────────┘     │  (Persistent)   │
                                                └─────────────────┘
```

**Matching Logic:**
1. Extract Amazon order ID from transaction memo (format: `XXX-XXXXXXX-XXXXXXX`)
2. Look up order in Amazon order history export
3. Match transaction to shipment by date proximity (bank charge date vs ship date)
4. Apply proportional allocation when charge differs from shipment total (gift cards, rewards)

**Proportional Allocation:**
When bank charges don't match item totals exactly (due to gift cards, rewards, etc.), amounts are distributed proportionally:
```
ratio = bank_charge / shipment_total
item_amount = item_total_owed * ratio
```
This ensures split transactions sum correctly to the actual charge while maintaining relative proportions.

**Categorization:**
1. Check persistent cache for previously categorized items
2. Batch uncached items (20 per API call) to Claude Haiku
3. Cache results for future runs

### Token Efficiency

The system minimizes Claude API costs through:

- **Batches API (--batch)** - 50% cheaper than synchronous API for backfill processing.
- **Category caching** - Items are cached by normalized name. Repeat purchases skip API calls entirely.
- **Prompt batching** - Items are grouped into chunks of 20 per API call (vs. 1 call per item).
- **Claude Haiku** - Uses the fastest, most cost-effective model for categorization.
- **Minimal prompts** - Prompts are concise, requesting only category names.
- **Email truncation** - Email content is truncated to 3000 characters for parsing.

Cache location: `data/processed/{account}/category_cache.json`

### Import ID Format

Transactions use unique import IDs to prevent duplicates:
```
AMZ2:{order_id}:{amount_cents}:{direction}
```
- `AMZ2` - Version prefix
- `order_id` - Amazon order number
- `amount_cents` - Amount in cents (no decimals)
- `direction` - `P` for purchase, `R` for refund

---

## Updating Existing Transactions

YNAB's API has a limitation: subtransaction memos cannot be updated after creation. To modify itemized transactions (e.g., fixing categories or adding quantity prefixes):

1. Delete the transaction from YNAB
2. Update the import_id with a new suffix (e.g., `:v4`)
3. Re-sync to create the transaction with updated data

The sync script tracks synced transactions by import_id to prevent duplicates. When deleting and recreating, use a new import_id suffix to avoid conflicts with YNAB's duplicate detection.

---

## Troubleshooting

### Many "NOT FOUND" Orders
Orders from a different Amazon account. If multiple household members share the same credit card but have separate Amazon accounts, export each person's order history and add to `data/amazon/order history/`. Note that Amazon data requests can take a few days to process.

### "NO MATCH" Orders
Items found but charge doesn't match any shipment. May be partial shipment, price adjustment, or split charge. Review manually in YNAB.

### YNAB Rate Limits
Sync script has automatic retry with backoff. Use `--dry-run` first to preview.

## Resources

- [YNAB](https://www.ynab.com/) - You Need A Budget budgeting software
- [YNAB API Documentation](https://api.ynab.com/)
- [Amazon Data Request](https://www.amazon.com/gp/privacycentral/dsar/preview.html) - Download your order history
- [Anthropic Claude](https://www.anthropic.com/) - AI for categorization
