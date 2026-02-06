# YNAB Amazon Itemizer

Categorize and itemize Amazon orders in YNAB using Claude AI. Two modes:

## Documentation Guidelines

**IMPORTANT:** When creating or updating documentation, examples, or comments:
- Use generic placeholder data, NOT real personal information
- Example order IDs: `123-4567890-1234567` (not real orders)
- Example emails: `user@example.com`, `receipts@example.com`
- Example amounts: `$12.34`, `$99.99` (not real transaction amounts)
- Example UUIDs: `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`
- Never include content from actual user conversations or real transactions
- **Automated**: Email-triggered Cloud Function (real-time)
- **Backfill**: Batch process from PDF statements

## Commands

```bash
# Parse PDF statements to CSV
python bank_to_ynab.py amazon-card data/amazon/statements/*.pdf -o out.csv

# Match orders and categorize (--batch for 50% cheaper async)
python process_transactions.py data/amazon/ynab_2025.csv

# Sync to YNAB
python sync_to_ynab.py all --dry-run   # preview
python sync_to_ynab.py all             # execute

# Regenerate audit CSVs from statements
python audit_statements.py

# Deploy Cloud Function
gcloud functions deploy process_gmail_push --gen2 --runtime python312 \
  --trigger-topic amazon-receipts --region us-central1 --timeout 120
```

## Code Style

- Python 3.12+
- Use f-strings, not % or .format()
- Type hints for public functions
- Keep functions focused and under 50 lines when practical

## YNAB Account IDs

Account IDs are stored in `config_private.py` (not committed). Copy from `config_private.example.py`:

```python
from config_private import YNAB_BUDGET_ID, YNAB_ACCOUNTS

budget_id = YNAB_BUDGET_ID
checking_id = YNAB_ACCOUNTS["checking"]
credit_card_id = YNAB_ACCOUNTS["credit_card"]
```

## Environment Variables

Load from `.env` file:
- `YNAB_TOKEN` - YNAB Personal Access Token (not YNAB_API_TOKEN)
- `ANTHROPIC_API_KEY` - For Claude categorization
- `GCP_PROJECT_ID` - GCP project for Cloud Function (Secret Manager, Firestore)

## Data Locations

- PDF statements: `data/{account}/statements/`
- Order history: `data/{account}/order history/`
- Processed cache: `data/processed/{account}/`
- Audit CSVs: `data/processed/{account}/audit/`
- Category cache: `data/processed/{account}/category_cache.json`

Note: `data/` directory is gitignored (contains personal financial data).

## Transaction Import IDs

Format: `AMZ2:{order_id}:{amount_cents}:{P|R}`
- P = purchase, R = refund
- Must be unique to prevent YNAB duplicates

## Sign Conventions (Credit Card)

- Purchases/Tips/Digital: Negative (increases debt)
- Payments/Refunds: Positive (reduces debt)

## Email Reply Corrections

Users can correct categorization errors by replying to summary emails in plain English.

**User flow:**
1. User receives categorization summary email
2. User replies: "categorize metamucil as personal care"
3. System parses correction via Claude, updates YNAB + category cache
4. System sends confirmation email with "(Updated)" marker on changed items
5. User can reply again to make more changes

**Key files:**
- `main.py`: `process_correction_reply()`, `extract_reply_text()`, `parse_correction_request()`, `apply_category_corrections()`
- `email_sender.py`: `send_correction_confirmation_email()`, `send_clarification_email()`
- `ynab_client.py`: `find_transaction_by_order_id()`, `get_transaction_by_id()`
- `ynab_writer.py`: `delete_transaction()`

**YNAB API limitation:** Cannot update `category_id` on split transactions (transactions with subtransactions). Workaround: delete the transaction and recreate it with corrected categories.

**Email routing:**
- Corrections detected by checking if reply is in a thread containing an order ID
- Automated emails (from receipts inbox) are skipped
- Confirmation emails: TO = user who sent correction, CC = receipts inbox

**Duplicate prevention:** Emails marked as processed in Firestore before handling to prevent race conditions from concurrent Cloud Function invocations.

## Skills

Skills codify common workflows with explicit permission requirements.

### Read-Only Skills (no write approval needed)
| Skill | Purpose |
|-------|---------|
| `/reconcile-account` | Compare YNAB balance vs audit CSVs |
| `/reconcile-amazon` | Reconcile Amazon card specifically |
| `/ynab-read` | Request YNAB API read access |

### Write Skills (explicit approval required)
| Skill | Purpose |
|-------|---------|
| `/ynab-write` | Create/update/delete YNAB transactions |
| `/file-write` | Create/modify local files (CSVs, cache) |
| `/sync-amazon-month YYYY-MM` | Sync month's transactions to YNAB |
| `/rebuild-amazon-ynab` | Full rebuild from audit CSVs |
| `/audit-statements` | Parse PDFs to generate audit CSVs |

## Permission Model

| Operation | Approval |
|-----------|----------|
| Read local files | Auto-approved |
| YNAB API reads | One-time session approval |
| **YNAB writes** | **Explicit approval with detailed summary** |
| **File writes** | **Explicit approval with file list** |
| **Git commits** | **Explicit approval with diff summary** |

**Write operations are NEVER executed without presenting a clear summary and receiving explicit "yes" approval.**

## Approval Workflow

All write operations follow this pattern:

1. **Collect** - Build complete list of proposed changes
2. **Present** - Show detailed summary:
   ```
   PROPOSED CHANGES
   ================
   [itemized list of every change]

   Approve? (yes/no)
   ```
3. **Wait** - Do NOT execute until user says "yes"
4. **Execute** - Only after explicit approval
5. **Report** - Confirm what was done

**YNAB API reads** require one-time session approval via AskUserQuestion before first API call. Subsequent reads are auto-approved for the session.

## Read/Write Separation

Code is split into read-only and write modules for permission control:

**Read-only modules** (auto-approved after session approval):
- `ynab_client.py` - YNAB API reads only (`_get()` method)
- `utils.py` - Utility functions, cache reads

**Write modules** (always require explicit approval):
- `ynab_writer.py` - YNAB creates/updates/deletes (`_write()` method)
- `file_writer.py` - File/cache writes
- `api_writer.py` - External API writes (Firestore, Gmail, Anthropic batch)

**Usage pattern:**
```python
from ynab_client import YNABClient  # Read-only - only GET requests
from ynab_writer import YNABWriter  # Write operations - POST/PUT/DELETE

client = YNABClient(token)
writer = YNABWriter(client)

transactions = client.get_transactions(budget_id)  # Session-approved
writer.create_transaction(budget_id, ...)          # Requires explicit approval
```

## Hook Enforcement

Hooks in `.claude/hooks/` enforce permission boundaries:

| Hook | Purpose |
|------|---------|
| `auto_approve_reads.py` | Auto-approve reads after session approval |
| `mark_read_session.py` | Track session state for read approval |
| `destructive_patterns.py` | Detect 120+ write patterns in Python/Bash |

**Detection patterns include:**
- Writer module imports (`from ynab_writer import`)
- File writes (`open(..., 'w')`, `.write()`, `.to_csv()`)
- HTTP writes (`requests.post()`, `method="POST"`)
- Git operations (`git commit`, `git push`)
- System modifications (`rm`, `mv`, `mkdir`)
