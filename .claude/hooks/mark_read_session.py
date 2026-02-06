#!/usr/bin/env python3
"""
Claude Code PreToolUse hook that marks the session as approved for read operations.

When a read-only operation is about to execute (meaning it was approved),
this hook creates/updates the session marker file so subsequent read
operations can be auto-approved.
"""

import json
import sys
import os

# Add hooks directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from destructive_patterns import is_safe_operation

# Session marker file - same as in auto_approve_reads.py
SESSION_MARKER = "/tmp/claude_read_session_approved"


def main():
    # Read the tool use request from stdin
    try:
        input_data = json.load(sys.stdin)
    except json.JSONDecodeError:
        sys.exit(0)

    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})

    # Check if this is a safe (read-only) operation
    is_safe, _ = is_safe_operation(tool_name, tool_input)

    if is_safe:
        # Create/update the session marker
        try:
            with open(SESSION_MARKER, "w") as f:
                f.write(f"Session approved at {os.popen('date').read().strip()}\n")
                f.write(f"Tool: {tool_name}\n")
        except OSError:
            pass  # Silently fail if we can't write the marker

    # Always exit successfully - don't block tool execution
    sys.exit(0)


if __name__ == "__main__":
    main()
