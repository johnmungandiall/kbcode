"""Web search tool (the Hermes idea, right-sized): a single free, no-API-key
backend via the ``ddgs`` package (DuckDuckGo) — not the multi-provider plugin
registry Hermes ships (``references/hermes-agent/agent/web_search_registry.py``),
which is overkill for a small self-contained agent with one built-in backend.
"""

from __future__ import annotations

import concurrent.futures as _cf
import json

# ddgs's own per-request timeout doesn't cap its internal multi-engine retry
# loop, so a slow/rate-limited response could otherwise hang the agent loop
# indefinitely. Run it in a worker thread with a hard wall-clock cap instead.
_SEARCH_TIMEOUT_SECS = 20


def _run_ddgs_search(query: str, limit: int) -> list[dict]:
    from ddgs import DDGS

    results = []
    with DDGS(timeout=10) as client:
        for i, hit in enumerate(client.text(query, max_results=limit)):
            if i >= limit:
                break
            results.append(
                {
                    "title": str(hit.get("title", "")),
                    "url": str(hit.get("href") or hit.get("url") or ""),
                    "description": str(hit.get("body", "")),
                }
            )
    return results


class WebToolsMixin:
    """web_search — DuckDuckGo search via the ``ddgs`` package, no API key needed."""

    def _tool_web_search(self, inp: dict) -> str:
        query = inp["query"]
        try:
            limit = int(inp.get("limit", 5))
        except (TypeError, ValueError):
            limit = 5
        limit = min(max(limit, 1), 20)

        try:
            import ddgs  # noqa: F401
        except ImportError:
            return "Error: the 'ddgs' package is not installed. Run: pip install ddgs"

        # A fresh single-worker pool per call: on timeout the blocking ddgs
        # call can't be cancelled, so a shared pool would serialize every
        # later search behind a previously-hung one.
        pool = _cf.ThreadPoolExecutor(max_workers=1)
        try:
            future = pool.submit(_run_ddgs_search, query, limit)
            try:
                results = future.result(timeout=_SEARCH_TIMEOUT_SECS)
            except _cf.TimeoutError:
                return (
                    f"Error: web search timed out after {_SEARCH_TIMEOUT_SECS}s "
                    "— DuckDuckGo may be rate-limiting. Try again shortly."
                )
        except Exception as exc:  # noqa: BLE001 - surface to the model
            return f"Error: web search failed: {exc}"
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

        if not results:
            return "No results found."
        return json.dumps(results, indent=2, ensure_ascii=False)
