"""Web tools (the Hermes idea, right-sized): ``web_search`` via the free
``ddgs`` package (DuckDuckGo) and ``fetch_url`` via stdlib urllib — no API
keys, no extra dependencies beyond ddgs. Not the multi-provider plugin
registry Hermes ships (``references/hermes-agent/agent/web_search_registry.py``),
which is overkill for a small self-contained agent.
"""

from __future__ import annotations

import concurrent.futures as _cf
import html as _html
import json
import re
import urllib.error
import urllib.request

# ddgs's own per-request timeout doesn't cap its internal multi-engine retry
# loop, so a slow/rate-limited response could otherwise hang the agent loop
# indefinitely. Run it in a worker thread with a hard wall-clock cap instead.
_SEARCH_TIMEOUT_SECS = 20
_FETCH_TIMEOUT_SECS = 20
_FETCH_MAX_BYTES = 2_000_000  # never download more than ~2 MB of a page
_FETCH_MAX_CHARS = 20000  # what fetch_url may return to the model
_FETCH_USER_AGENT = "Mozilla/5.0 (compatible; kbcode/1.0; +https://github.com/johnmungandiall/kbcode)"

_TAG_DROP = re.compile(r"(?is)<(script|style|noscript|template|svg|head)\b.*?</\1\s*>")
_TAG_BREAK = re.compile(r"(?i)</?(p|div|br|li|tr|h[1-6]|section|article|blockquote|pre)\b[^>]*>")
_TAG_ANY = re.compile(r"(?s)<[^>]+>")


def _html_to_text(markup: str) -> str:
    """Best-effort HTML→plain-text: drop non-content blocks, keep block
    boundaries as newlines, strip the rest of the tags, unescape entities."""
    text = _TAG_DROP.sub(" ", markup)
    text = _TAG_BREAK.sub("\n", text)
    text = _TAG_ANY.sub(" ", text)
    text = _html.unescape(text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n\s*", "\n\n", text)
    return text.strip()


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


def _fetch(url: str) -> tuple[str, str]:
    """Download ``url`` and return (content_type, decoded body)."""
    req = urllib.request.Request(url, headers={"User-Agent": _FETCH_USER_AGENT})
    with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT_SECS) as resp:
        ctype = resp.headers.get("Content-Type", "")
        raw = resp.read(_FETCH_MAX_BYTES)
    charset = "utf-8"
    m = re.search(r"charset=([\w-]+)", ctype)
    if m:
        charset = m.group(1)
    try:
        body = raw.decode(charset, errors="replace")
    except LookupError:
        body = raw.decode("utf-8", errors="replace")
    return ctype, body


class WebToolsMixin:
    """web_search — DuckDuckGo search via ``ddgs``; fetch_url — read a page
    via stdlib urllib. Neither needs an API key."""

    def _tool_fetch_url(self, inp: dict) -> str:
        url = str(inp["url"]).strip()
        if not url.lower().startswith(("http://", "https://")):
            return "Error: fetch_url only supports http:// and https:// URLs."
        # Same hang-proofing as web_search: urllib's timeout covers connect/read
        # calls individually, not total wall-clock, so cap it in a worker thread.
        pool = _cf.ThreadPoolExecutor(max_workers=1)
        try:
            future = pool.submit(_fetch, url)
            try:
                ctype, body = future.result(timeout=_FETCH_TIMEOUT_SECS + 5)
            except _cf.TimeoutError:
                return f"Error: fetching {url} timed out after {_FETCH_TIMEOUT_SECS + 5}s."
        except urllib.error.HTTPError as exc:
            return f"Error: {url} returned HTTP {exc.code} {exc.reason}."
        except Exception as exc:  # noqa: BLE001 - surface to the model
            return f"Error: failed to fetch {url}: {exc}"
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

        if "html" in ctype.lower() or body.lstrip()[:200].lower().startswith(("<!doctype", "<html")):
            text = _html_to_text(body)
        else:
            text = body.strip()  # JSON / plain text / etc. — return as-is
        if not text:
            return f"(fetched {url} but found no readable text — content type: {ctype or 'unknown'})"
        if len(text) > _FETCH_MAX_CHARS:
            text = text[:_FETCH_MAX_CHARS] + f"\n[...truncated at {_FETCH_MAX_CHARS} chars...]"
        return f"Fetched {url} ({ctype or 'unknown content type'}):\n\n{text}"

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
