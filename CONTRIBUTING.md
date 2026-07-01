# Contributing to kbcode

Thanks for considering a contribution. This project is small on purpose —
please read this before sending a PR so it lands cleanly.

## Setup

```bash
git clone https://github.com/johnmungandiall/kbcode.git
cd kbcode
pip install -e ".[dev]"   # kbcode itself + pytest + ruff
```

On Windows, set `PYTHONIOENCODING=utf-8` before running anything that prints
the UI — the terminal uses emoji/box-drawing characters the default `cp1252`
console can't encode.

## Before you open a PR

```bash
pytest -q            # tests must pass
ruff check .          # lint must be clean
python -m py_compile kbcode/*.py   # the de-facto build check
```

CI (`.github/workflows/ci.yml`) runs all three on push/PR across Python
3.10/3.12 on Ubuntu and Windows — a red check blocks review.

## Coding standards

- **No comments unless the WHY is non-obvious.** Don't explain what the code
  does — name things so it's clear. A comment earns its place by capturing a
  hidden constraint, a workaround, or a reason a future reader would
  otherwise have to reconstruct from git blame.
- **No speculative abstraction.** Don't add config flags, base classes, or
  "for future use" hooks for something not needed yet. Three similar lines
  beat a premature abstraction.
- **Match the existing shape of the file you're editing** before introducing
  a new pattern — this codebase deliberately keeps `agent.py` about *logic*
  and `ui.py` about *looks*, tools as `_tool_<name>` methods with a matching
  schema, etc. See `CLAUDE.md` for the full architecture map and the "When
  adding things" section for where new tools/commands/modes/providers go.
- **Every new capability should trace back to one of the five reference
  ideas** this project blends (Claude Code, Hermes, claude-kb, Kilo Code,
  openclaw) — see `CLAUDE.md`'s intro. If it doesn't fit any of them, it
  probably doesn't belong here.
- Type hints on new public functions; `from __future__ import annotations`
  is already at the top of every module.

## Tests

New behavior needs a test. Existing coverage lives in `tests/` and mirrors
the module it exercises (`tests/test_repair.py` for `kbcode/repair.py`,
etc.) — integration-style tests that exercise the agent loop against a fake
provider live in `tests/test_agent.py`. Prefer a focused unit test over a
full agent-loop test when the thing you're testing is a pure function.

## Commit / PR style

- Keep commits scoped to one change; write the message around *why*, not a
  restatement of the diff.
- Reference the `IMPROVEMENTS.md` item number in the PR description if your
  change addresses one (e.g. "addresses #6.4").
- Don't bump `kbcode.__version__` in a feature PR — releases are cut
  separately (bump `__version__`, tag `vX.Y.Z`, push).

## Boundaries

- `references/` (cloned third-party source for studying the five ideas) is
  gitignored and not part of the product — never import from it.
- `.kbcode/` and `.env` are per-machine/secret and gitignored; don't commit
  anything from either.
