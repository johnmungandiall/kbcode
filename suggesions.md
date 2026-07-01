
### 🔴 High-value / high-impact

1. **Plugin/extension system** — Tools are hardcoded in `_base_schemas` + `_tool_*` methods. A lightweight plugin interface (drop a `.py` in `.kbcode/plugins/`) would let users add tools without forking the project. This is the biggest architectural unlock.

2. **MCP (Model Context Protocol) support** — Anthropic's MCP is becoming a standard for tool servers. Adding an MCP client transport would give kbcode access to hundreds of community tools (databases, APIs, file systems) with zero new tool code.

3. **Multi-file edit batching** — The agent currently makes one `edit_file` call per change. A "plan → show diff → apply all" mode (like Cursor's multi-file edit) would cut latency and approval friction on big refactors.

4. **Web search / URL fetch tool** — A common gap vs. cloud-hosted agents. Even a simple `fetch_url` tool (with size limits + caching) would unlock doc lookups, API research, etc.

### 🟡 Medium value

5. **Token usage display in streaming** — Show live token counts during streaming (like Claude Code does), not just post-hoc via `/insights`.

6. **Cost budgets / alerts** — Set a per-session or daily token budget in config; warn before exceeding. The pricing tables are already there (`pricing.py`).

7. **Structured output mode** — A `/json` or `/structured` toggle so the agent can return parseable results for scripting/CI use (already has one-shot mode; this would be for non-interactive pipelines).

8. **Undo/redo for file edits** — `/rollback` uses shadow git, but a simpler "undo last edit" command (stack-based) would cover the common case faster.

9. **Diff-based context for compaction** — Instead of summarizing old turns into prose, compact by keeping only the latest state of each file touched. Would preserve more precision.

10. **Workspace/project detection** — Auto-detect `.git`, `pyproject.toml`, `package.json`, etc. and adjust tool behavior (e.g., auto-run tests after edits, detect the test framework).

### 🟢 Quick wins

11. **`/diff` command** — Show unstaged changes in the working tree (the checkpoint git already has the plumbing).

12. **`/run-last` command** — Re-run the last shell command without retyping it.

13. **Fuzzy file picker for `/open`** — The autocomplete exists, but a fzf-style fuzzy matcher (using prompt_toolkit's fuzzy select) would be snappier.

14. **Clipboard paste mode** — Auto-detect when the user pastes multi-line code (e.g., from an error message) and format it properly instead of interpreting line-by-line.

15. **Test coverage gaps** — The changelog mentions ~211 tests across 22 files, but some newer features (streaming, parallel tool exec, compaction) may have thin coverage. A coverage report would reveal where to add tests.