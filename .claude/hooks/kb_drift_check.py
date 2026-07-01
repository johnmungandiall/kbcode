#!/usr/bin/env python3
"""Stop hook: before the session ends, run tools/kb-check.sh. If any kb/ note has a
BROKEN explicit-file pointer (kb-check exits non-zero), block the stop ONCE and feed the
drift back so Claude fixes it before finishing.

Safety: guarded by `stop_hook_active` so it nudges at most once and never loops; any
tooling error just allows the stop (never traps the user). kb-check only exits non-zero
on genuinely broken full-path pointers, so this is low-false-positive. No-op when the
checker is absent.

Stdlib only (no jq / no third-party deps); works on Windows + Unix.
"""
import json
import os
import subprocess
import sys


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}

    # If we are here because THIS hook already blocked once, let the stop proceed.
    if data.get("stop_hook_active"):
        return

    root = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    checker = os.path.join(root, "tools", "kb-check.sh")
    if not os.path.isfile(checker):
        return

    try:
        result = subprocess.run(
            ["bash", "tools/kb-check.sh"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except Exception:
        return  # never block on a tooling hiccup

    if result.returncode == 0:
        return  # all kb/ pointers resolve -> allow stop

    drift = ((result.stdout or "") + (result.stderr or "")).strip()
    reason = (
        "KB drift detected before stop: kb/ notes have broken pointers. Fix them, "
        "update the affected note(s), then re-run `bash tools/kb-check.sh` until it "
        "reports 0 broken:\n\n" + drift
    )
    print(json.dumps({"decision": "block", "reason": reason}))


if __name__ == "__main__":
    main()
