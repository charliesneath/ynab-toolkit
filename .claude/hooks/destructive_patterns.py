"""
Patterns that indicate potentially destructive operations.

Used by permission hooks to identify operations that should require
manual approval rather than being auto-approved.
"""

import re

# Python code patterns that modify state
DESTRUCTIVE_PYTHON_PATTERNS = [
    # Writer module imports (explicit destructive intent)
    r"from\s+ynab_writer\s+import",          # YNAB write operations
    r"from\s+file_writer\s+import",          # File write operations
    r"from\s+api_writer\s+import",           # External API writes
    r"import\s+ynab_writer",                 # YNAB write operations
    r"import\s+file_writer",                 # File write operations
    r"import\s+api_writer",                  # External API writes
    r"\bYNABWriter\s*\(",                    # Instantiating YNAB writer

    # Aliased imports (bypass attempts)
    r"as\s+ynab_writer",                     # import x as ynab_writer
    r"as\s+file_writer",                     # import x as file_writer
    r"as\s+api_writer",                      # import x as api_writer

    # Dynamic imports (bypass attempts)
    r"__import__\s*\(\s*['\"]ynab_writer",   # __import__('ynab_writer')
    r"__import__\s*\(\s*['\"]file_writer",   # __import__('file_writer')
    r"__import__\s*\(\s*['\"]api_writer",    # __import__('api_writer')
    r"importlib\.import_module\s*\(\s*['\"]ynab_writer",
    r"importlib\.import_module\s*\(\s*['\"]file_writer",
    r"importlib\.import_module\s*\(\s*['\"]api_writer",

    # Direct write method calls (YNABWriter._write is the only write path)
    r"\._write\s*\(",                           # YNABWriter._write() calls

    # Firestore write operations (when not using api_writer)
    r"\.set\s*\(\s*\{",                      # doc.set({...})
    r"\.create\s*\(\s*\{",                   # doc.create({...})
    r"\.update\s*\(\s*\{",                   # doc.update({...})

    # Gmail send operations
    r"\.messages\(\)\.send\s*\(",            # gmail.users().messages().send()
    r"\.watch\s*\(\s*userId",                # gmail watch setup

    # File writes
    r"open\s*\([^)]*['\"][wa]['\"]",        # open(file, 'w') or 'a'
    r"\.write\s*\(",                         # file.write()
    r"\.writelines\s*\(",                    # file.writelines()
    r"pathlib\.Path.*\.write",               # Path.write_text/write_bytes

    # File/directory modifications
    r"\bos\.remove\s*\(",                    # os.remove()
    r"\bos\.unlink\s*\(",                    # os.unlink()
    r"\bos\.rmdir\s*\(",                     # os.rmdir()
    r"\bos\.rename\s*\(",                    # os.rename()
    r"\bos\.replace\s*\(",                   # os.replace()
    r"\bos\.makedirs\s*\(",                  # os.makedirs()
    r"\bos\.mkdir\s*\(",                     # os.mkdir()
    r"\bshutil\.(rmtree|move|copy|copytree)", # shutil operations

    # Pandas/data serialization writes
    r"\.to_csv\s*\(",                        # DataFrame.to_csv()
    r"\.to_json\s*\(",                       # DataFrame.to_json()
    r"\.to_excel\s*\(",                      # DataFrame.to_excel()
    r"\.to_parquet\s*\(",                    # DataFrame.to_parquet()
    r"\.to_pickle\s*\(",                     # DataFrame.to_pickle()
    r"\bjson\.dump\s*\(",                    # json.dump() to file
    r"\bpickle\.dump\s*\(",                  # pickle.dump()
    r"\byaml\.dump\s*\(",                    # yaml.dump()

    # Subprocess/system execution
    r"\bos\.system\s*\(",                    # os.system()
    r"\bsubprocess\.(run|call|Popen)",       # subprocess
    r"\bexec\s*\(",                          # exec()
    r"\beval\s*\(",                          # eval()

    # HTTP write methods
    r"requests\.(post|put|patch|delete)\s*\(",
    r"\.post\s*\(",                          # session.post()
    r"\.put\s*\(",                           # session.put()
    r"\.patch\s*\(",                         # session.patch()
    r"\.delete\s*\(",                        # session.delete()
    r"method\s*=\s*['\"]POST['\"]",
    r"method\s*=\s*['\"]PUT['\"]",
    r"method\s*=\s*['\"]PATCH['\"]",
    r"method\s*=\s*['\"]DELETE['\"]",

    # Database modifications
    r"\.(execute|executemany)\s*\(\s*['\"]?(INSERT|UPDATE|DELETE|DROP|CREATE|ALTER)",
    r"\.commit\s*\(",                        # transaction commit

    # YNAB-specific write operations (direct calls, backwards compat)
    r"create_transaction",                   # YNAB API writes
    r"update_transaction",
    r"delete_transaction",
    r"create_split_transaction",
]

# Bash commands that modify state
DESTRUCTIVE_BASH_PATTERNS = [
    # File operations
    r"\brm\s",                               # rm
    r"\brmdir\s",                            # rmdir
    r"\bmv\s",                               # mv (move/rename)
    r"\bcp\s",                               # cp (copy can overwrite)
    r"\btouch\s",                            # touch
    r"\bmkdir\s",                            # mkdir
    r"\bchmod\s",                            # chmod
    r"\bchown\s",                            # chown

    # Redirects that write - require filename-like target after redirect
    # Exclude f-string alignment specs like {x:>10} by requiring whitespace before >
    # and ensuring it's not preceded by : (f-string format spec)
    r"(?<!:)\s+>\s*[/\w~]",                  # > redirect to file/path (not f-string :>)
    r"(?<!:)\s+>>\s*[/\w~]",                 # >> redirect to file/path

    # Git write operations
    r"\bgit\s+(push|commit|merge|rebase|reset|checkout|stash|cherry-pick|revert)",
    r"\bgit\s+branch\s+-[dD]",               # git branch -d (delete)

    # Package managers (install = state change)
    r"\bpip\s+install",
    r"\bnpm\s+(install|uninstall|update)",
    r"\bbrew\s+(install|uninstall|upgrade)",

    # Dangerous system commands
    r"\bsudo\s",                             # sudo anything
    r"\bkill\s",                             # kill processes
    r"\bpkill\s",                            # pkill
    r"\bsystemctl\s",                        # systemd
    r"\bservice\s",                          # services

    # Cloud/deploy operations
    r"\bgcloud\s.*(deploy|delete|create)",
    r"\baws\s.*(delete|put|create|update)",
    r"\bkubectl\s+(apply|delete|create)",
]


def contains_destructive_python(code: str) -> tuple[bool, str | None]:
    """
    Check if Python code contains destructive patterns.

    Returns:
        (is_destructive, matched_pattern) - True and the pattern if destructive
    """
    for pattern in DESTRUCTIVE_PYTHON_PATTERNS:
        if re.search(pattern, code, re.IGNORECASE):
            return True, pattern
    return False, None


def contains_destructive_bash(command: str) -> tuple[bool, str | None]:
    """
    Check if a bash command contains destructive patterns.

    Returns:
        (is_destructive, matched_pattern) - True and the pattern if destructive
    """
    for pattern in DESTRUCTIVE_BASH_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            return True, pattern
    return False, None


def is_safe_operation(tool_name: str, tool_input: dict) -> tuple[bool, str | None]:
    """
    Check if a tool operation is safe (read-only).

    Args:
        tool_name: The Claude Code tool name (Bash, Read, Edit, etc.)
        tool_input: The tool's input parameters

    Returns:
        (is_safe, reason) - True if safe, False with reason if not
    """
    # These tools are always read-only
    if tool_name in ("Read", "Glob", "Grep"):
        return True, None

    # These tools are always destructive
    if tool_name in ("Write", "Edit", "NotebookEdit"):
        return False, f"{tool_name} modifies files"

    # Bash requires inspection
    if tool_name == "Bash":
        command = tool_input.get("command", "")
        bash_wrapper = command

        # For heredoc commands, only check bash patterns on the wrapper, not content
        heredoc_match = re.search(r"<<\s*['\"]?EOF['\"]?(.*?)EOF", command, re.DOTALL)
        if heredoc_match:
            # Extract just the bash wrapper (before heredoc) for bash pattern checks
            bash_wrapper = command[:heredoc_match.start()]

        # For -c "code" style, also extract just the bash wrapper (before quoted code)
        # Match: python3 -c "code" or python -c 'code' (including multi-line)
        python_code = None

        # Try double-quoted multi-line first
        c_double_match = re.search(r'(python3?\s+-c\s+)"(.*)"', command, re.DOTALL)
        if c_double_match:
            python_code = c_double_match.group(2)
            # Only check bash patterns on part before the Python code
            bash_wrapper = command[:c_double_match.start(2)]
        else:
            # Try single-quoted
            c_single_match = re.search(r"(python3?\s+-c\s+)'(.*)'", command, re.DOTALL)
            if c_single_match:
                python_code = c_single_match.group(2)
                bash_wrapper = command[:c_single_match.start(2)]

        # Check for destructive bash patterns (only on bash wrapper, not Python content)
        is_destructive, pattern = contains_destructive_bash(bash_wrapper)
        if is_destructive:
            return False, f"Bash command matches destructive pattern: {pattern}"

        if python_code:
            is_destructive, pattern = contains_destructive_python(python_code)
            if is_destructive:
                return False, f"Inline Python (-c) matches destructive pattern: {pattern}"

        # Check inline Python (heredoc)
        heredoc_match = re.search(r"<<\s*['\"]?EOF['\"]?(.*?)EOF", command, re.DOTALL)
        if heredoc_match:
            python_code = heredoc_match.group(1)
            is_destructive, pattern = contains_destructive_python(python_code)
            if is_destructive:
                return False, f"Inline Python matches destructive pattern: {pattern}"

        # If no destructive patterns found, consider it safe
        return True, None

    # Unknown tools require approval
    return False, f"Unknown tool: {tool_name}"
