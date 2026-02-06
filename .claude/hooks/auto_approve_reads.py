#!/usr/bin/env python3
"""
Claude Code PermissionRequest hook that auto-approves read-only operations
AFTER the user has approved the first read operation in the session.

First read operation → requires manual approval
Subsequent reads → auto-approved (if session marker exists)

Operations that might be destructive always require manual approval.
"""

import json
import sys
import os
import time

# Add hooks directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from destructive_patterns import is_safe_operation

# Session marker file - created by mark_read_session.py PreToolUse hook
SESSION_MARKER = "/tmp/claude_read_session_approved"

# Session timeout in seconds (8 hours)
SESSION_TIMEOUT = 8 * 60 * 60


def is_session_approved() -> bool:
    """Check if read operations have been approved this session."""
    if not os.path.exists(SESSION_MARKER):
        return False

    try:
        marker_time = os.path.getmtime(SESSION_MARKER)
        age = time.time() - marker_time
        return age < SESSION_TIMEOUT
    except OSError:
        return False


DEBUG_LOG = "/tmp/claude_hook_debug.log"


def debug_log(msg: str):
    """Write debug message to log file."""
    with open(DEBUG_LOG, "a") as f:
        f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")


def main():
    # Read the permission request from stdin
    try:
        input_data = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        debug_log(f"JSON parse error: {e}")
        print(f"Error parsing input: {e}", file=sys.stderr)
        sys.exit(1)

    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})

    debug_log(f"Tool: {tool_name}")
    debug_log(f"Input keys: {list(tool_input.keys())}")

    # Check if operation is safe (read-only)
    is_safe, reason = is_safe_operation(tool_name, tool_input)
    debug_log(f"is_safe={is_safe}, reason={reason}")

    session_ok = is_session_approved()
    debug_log(f"session_approved={session_ok}")

    if is_safe:
        # Only auto-approve if session has been approved
        if session_ok:
            debug_log("AUTO-APPROVING")
            print(json.dumps({
                "hookSpecificOutput": {
                    "hookEventName": "PermissionRequest",
                    "decision": {
                        "behavior": "allow"
                    }
                }
            }))
        else:
            debug_log("Safe but no session - manual approval needed")
    else:
        debug_log(f"Not safe: {reason}")

    sys.exit(0)


if __name__ == "__main__":
    main()
