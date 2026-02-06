# Skill: ynab-write

Execute YNAB write operations (create/update/delete transactions) with explicit approval.

## Permission Model

| Operation | Approval Required |
|-----------|-------------------|
| **Create transactions** | **Explicit approval with full details** |
| **Update transactions** | **Explicit approval showing old → new** |
| **Delete transactions** | **Explicit approval with reason** |

**YNAB writes are NEVER executed without presenting a detailed summary and receiving explicit "yes" approval.**

## Instructions

When modifying YNAB data, follow this workflow:

### 1. Collect Operations

Before making any changes, I will build a list of all proposed operations:

```
PROPOSED YNAB CHANGES
=====================

ADD (X transactions):
  - [date] [amount] [payee] [account]
  - [date] [amount] [payee] [account]

UPDATE (X transactions):
  - [id] [field]: [old] → [new]

DELETE (X transactions):
  - [date] [amount] [payee] [reason]

Net impact: [+/-$X.XX]
```

### 2. Wait for Approval

I will ask: "Approve these YNAB changes? (yes/no)"

- **Do NOT execute** until user explicitly approves
- If user says "no" or asks for changes, revise the list
- User can approve all, approve some, or reject

### 3. Execute Approved Changes

Only after approval:
- Execute the API calls
- Report success/failure for each operation
- Show final account balance

## Code Pattern

```python
from ynab_client import YNABClient  # Read-only
from ynab_writer import YNABWriter  # Write operations

client = YNABClient(token)
writer = YNABWriter(client)

# All writes go through YNABWriter
writer.create_transaction(budget_id, account_id, ...)
writer.update_transaction(budget_id, transaction_id, ...)
writer.delete_transaction(budget_id, transaction_id)
```

## Hook Enforcement

Importing from `ynab_writer` triggers permission checks via `destructive_patterns.py`. The hook detects:
- `from ynab_writer import`
- `import ynab_writer`
- Direct write method calls (`create_transaction`, `update_transaction`, etc.)

## Usage

This skill is invoked automatically when I need to write to YNAB. You can also invoke it explicitly:

```
/ynab-write
```

Then describe what changes you want to make.

## Example Flow

```
User: Add the missing $50.00 refund from today

Claude:
PROPOSED YNAB CHANGES
=====================
ADD (1 transaction):
  - 2026-01-22  +$50.00  Refund - Example Store  [Checking]

Net impact: +$50.00

Approve these YNAB changes? (yes/no)

User: yes

Claude: ✓ Added: 2026-01-22 +$50.00 Refund - Example Store
        New balance: $1,234.56
```
