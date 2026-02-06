# Skill: ynab-read

Request permission to read YNAB data via API.

## Permission Model

| Operation | Approval Required |
|-----------|-------------------|
| YNAB API reads (GET) | One-time session approval |
| **YNAB API writes (POST/PUT/DELETE)** | **Explicit approval per operation** |

**All write operations require presenting a detailed summary and receiving explicit "yes" approval. This skill is READ-ONLY.**

## Instructions

### 1. Request Session Approval

Before any YNAB API calls, use `AskUserQuestion`:

```
May I access the YNAB API to fetch [specific data]?

Data to be accessed:
- [Account name] transactions
- [Date range]
- [Other data: categories, balances, etc.]

This is a READ-ONLY operation. No changes will be made.
```

### 2. After Approval

Once approved, subsequent YNAB reads in the same session proceed without re-prompting.

### 3. Code Pattern

```python
from ynab_client import YNABClient  # Read-only module - only GET requests

client = YNABClient(token)
accounts = client.get_accounts(budget_id)      # GET
transactions = client.get_transactions(...)    # GET
categories = client.get_categories(...)        # GET
```

**Note:** `ynab_client.py` contains ONLY read operations. Write operations live in `ynab_writer.py` and trigger separate permission checks.

## Session Management

The `auto_approve_reads.py` hook manages read session state:
- First YNAB read: requires manual approval
- Subsequent reads: auto-approved for session duration
- Session expires after 8 hours of inactivity

## Usage

This skill is invoked implicitly when YNAB data access is needed:

```
/ynab-read
```

Or naturally: "show me recent transactions from checking"
