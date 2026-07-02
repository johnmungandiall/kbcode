# Flexible Search/Replace with Multiple Strategies

The Aider idea (#3 from `references/aider-features-for-kbcode.md`): when an
`edit_file`/`edit_files` exact match fails — often because the model gets
indentation slightly wrong or adds extra blank lines — kbcode now tries a
sequence of progressively more lenient strategies before giving up.

## Module
[kbcode/tools/edit_strategies.py](../kbcode/tools/edit_strategies.py)

## Strategy order (decreasing strictness)
1. **exact** — strict string equality (the original behaviour)
2. **strip-blanks** — strip leading/trailing blank lines, then exact
3. **indent** — normalize indentation (relative indent), then exact
4. **strip+indent** — both of the above
5. **fuzzy** — line-based similarity via difflib (≥70 % match, requires unique best match)

## Uniqueness
Every strategy checks for uniqueness. Strategies 3–5 will also fail with
"ambiguous — appears multiple times" if the normalized/fuzzy match isn't unique.

## Integration
- `file.py` `_tool_edit_file` calls `try_edit()` and mentions the strategy in
  the permission prompt (e.g. `edit foo.py  [strategy: indent]`)
- `file.py` `_tool_edit_files` calls `try_edit()` per edit in the validation
  pass, then `try_single_strategy()` in the apply pass; strategy names appear
  in the batch summary and per-file result line
- Pure stdlib (`difflib`) — zero new dependencies

## Design
- `StrategyFunc = Callable[[str, str, str], str]` — (file_text, old, new) → new_text
- Each strategy raises `ValueError` on failure with a descriptive message
- `try_edit()` iterates `_STRATEGIES`, collects errors, raises with full trace on total failure
- `try_single_strategy()` is the thin wrapper for batch mode

See also [[tools-and-repair]], [[architecture]].
