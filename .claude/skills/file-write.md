# Skill: file-write

Execute file write operations (cache updates, CSV exports) with explicit approval.

## Permission Model

| Operation | Approval Required |
|-----------|-------------------|
| Read files (CSV, JSON, cache) | Auto-approved |
| **Create files** | **Explicit approval with path and content summary** |
| **Modify files** | **Explicit approval with change summary** |
| **Delete files** | **Explicit approval with reason** |

**File writes are NEVER executed without presenting a clear summary and receiving explicit "yes" approval.**

## Instructions

### 1. Collect Proposed Changes

Before writing any files, list ALL proposed operations:

```
PROPOSED FILE CHANGES
=====================

CREATE:
  - path/to/new_file.csv
    Content: X rows, [brief description]

UPDATE:
  - path/to/cache.json
    Change: Adding X entries to category cache

DELETE:
  - path/to/obsolete.csv
    Reason: [why this file should be removed]

Total: X files affected
```

### 2. Wait for Explicit Approval

Ask: **"Approve these file changes? (yes/no)"**

- Do NOT execute until user says "yes"
- User can approve all, approve some, or reject
- If rejected, ask what changes they want

### 3. Execute Only After Approval

Use `file_writer.py` functions for all writes:

```python
from file_writer import save_cache, save_csv_report

save_cache(cache_file, data)
save_csv_report(transactions, csv_file, mapping)
```

### 4. Report Results

After execution, confirm what was done:

```
FILE CHANGES COMPLETE
=====================
✓ Created: path/to/file.csv (X rows)
✓ Updated: path/to/cache.json
```

## Hook Enforcement

Importing from `file_writer` triggers permission checks via `destructive_patterns.py`. The hook detects:
- `from file_writer import`
- `import file_writer`
- Direct file write operations (`.write()`, `open(..., 'w')`)

## Usage

```
/file-write
```

Or naturally: "export transactions to CSV" / "update the category cache"
