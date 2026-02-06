# Skill: approval-flow

General approval workflow for any state-modifying operations.

## Permission Model

| Operation | Approval Required |
|-----------|-------------------|
| Read files, API GETs, analysis | Auto-approved (after session approval for APIs) |
| **YNAB writes** | **Explicit approval with transaction list** |
| **File writes** | **Explicit approval with file list** |
| **Git commits/push** | **Explicit approval with diff summary** |
| **Cloud deployments** | **Explicit approval with change summary** |

**Write operations are NEVER executed without presenting a clear summary and receiving explicit "yes" approval.**

## Core Principle

**Read operations**: Execute automatically (no approval needed)
**Write operations**: Batch, summarize, and get explicit approval before executing

## What Requires Approval

Any operation that creates, modifies, or deletes:
- YNAB transactions (add/update/delete)
- Files (write/edit/delete)
- Git commits and pushes
- API calls that modify state (POST/PUT/DELETE)
- Database changes
- Cloud resource modifications (gcloud, AWS, etc.)

## What Does NOT Require Approval

- Reading files
- Listing directories
- API GET requests
- Git status/diff/log
- Running analysis scripts that only output data
- Searching/grepping

## Approval Flow

### Step 1: Collect Operations

Before executing any write operations, collect them into a summary:

```
PROPOSED CHANGES
================
[Category] (X operations):
  - [description of change 1]
  - [description of change 2]
  ...

Impact: [summary of what will change]
```

### Step 2: Present and Wait

Show the summary and ask:
> "Approve these changes? (yes/no)"

**Do NOT execute until user explicitly approves.**

### Step 3: Handle Response

- **"yes"** → Execute all approved operations, report results
- **"no"** → Cancel, ask what to change
- **Partial approval** → User can specify which items to approve
- **Questions** → Answer, then re-present for approval

### Step 4: Execute and Report

After approval:
- Execute each operation
- Report success/failure
- Show final state

## Examples

### YNAB Changes
```
PROPOSED YNAB CHANGES
=====================
ADD (2 transactions):
  - 2026-01-22  +$50.00   Store Refund    [Checking]
  - 2026-01-09  -$175.00  CHECK #404      [Checking]

DELETE (1 transaction):
  - 2025-05-05  -$140.00  Duplicate entry

Net impact: -$265.00

Approve these changes? (yes/no)
```

### File Changes
```
PROPOSED FILE CHANGES
=====================
EDIT (1 file):
  - settings.json: Add 3 new permission patterns

CREATE (1 file):
  - skills/new-skill.md

Approve these changes? (yes/no)
```

### Git Operations
```
PROPOSED GIT OPERATIONS
=======================
COMMIT:
  - Message: "Add reconciliation skills"
  - Files: 4 changed, 156 insertions

PUSH:
  - Branch: main → origin/main

Approve these changes? (yes/no)
```

## Usage

This skill is automatically applied to all my operations. You don't need to invoke it manually.

To check if I'm following the workflow:
```
/approval-flow
```
