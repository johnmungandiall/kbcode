#!/usr/bin/env python3
"""PostToolUse hook (Write|Edit|MultiEdit): once per session, after Claude edits a
source/config file the kb/ notes map, remind it to update the matching kb/ note in the
SAME session (the CLAUDE.md / kb/about-kb.md auto-maintain rule). Non-blocking — only
injects context. Framework-agnostic: it hardcodes NO language's extensions; it reminds
for any edit OUTSIDE kb/, .claude/, .git/ and the top-level docs.

Stdlib only (no jq / no third-party deps); works on Windows + Unix.
"""
import json
import os
import sys
import tempfile

# Editing these never triggers a reminder (they are not "source the KB maps").
SKIP_DIRS = ("/kb/", "/.claude/", "/.git/", "/node_modules/")
SKIP_NAMES = ("claude.md", "memory.md", "readme.md")


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return

    tool_input = data.get("tool_input") or {}
    tool_resp = data.get("tool_response") or {}
    fp = tool_input.get("file_path")
    if not fp and isinstance(tool_resp, dict):
        fp = tool_resp.get("filePath")
    if not fp:
        return

    norm = fp.replace("\\", "/").lower()
    base = os.path.basename(norm)
    if any(d in norm for d in SKIP_DIRS) or base in SKIP_NAMES:
        return

    # Remind at most once per session to avoid noise on multi-edit sessions.
    sid = str(data.get("session_id") or "nosid")
    safe_sid = "".join(c for c in sid if c.isalnum() or c in "-_") or "nosid"
    marker = os.path.join(tempfile.gettempdir(), "claude-kb-reminder-%s.flag" % safe_sid)
    if os.path.exists(marker):
        return
    try:
        open(marker, "w").close()
    except Exception:
        pass

    msg = (
        "KB upkeep (CLAUDE.md rule): you changed `%s` this session. Before ending "
        "your turn, update the affected kb/ note(s) in the SAME session — refresh any "
        "path:line pointers and changed behavior — then run `bash tools/kb-check.sh` "
        "and confirm it reports 0 broken. For a non-trivial change, dispatch the "
        "kb-maintainer subagent." % os.path.basename(fp)
    )
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": msg,
        }
    }))


if __name__ == "__main__":
    main()
