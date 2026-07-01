"""Regex-based secret redaction for tool output (the Hermes idea).

A `run_command` that does `cat .env`, `env`, or `curl -H "Authorization: ..."`
would otherwise dump a live credential straight into the model's context (and
from there into the transcript, the KB, or memory). This masks the common
shapes of API keys, tokens, and credentials before that output is returned to
the model or shown in the UI. Non-matching text passes through unchanged.
"""

from __future__ import annotations

import os
import re
import shlex

# Snapshot at import time so nothing that happens later (env mutation inside
# the *parent* process) can silently disable redaction mid-session. On by
# default; opt out with KBCODE_REDACT_SECRETS=false in .env for the rare case
# where you're debugging the redactor itself and need raw values.
_REDACT_ENABLED = os.getenv("KBCODE_REDACT_SECRETS", "true").lower() in {"1", "true", "yes", "on"}

# Known API key prefixes -- match the prefix + contiguous token chars.
_PREFIX_PATTERNS = [
    r"sk-[A-Za-z0-9_-]{10,}",           # OpenAI / OpenRouter / Anthropic (sk-ant-*)
    r"ghp_[A-Za-z0-9]{10,}",            # GitHub PAT (classic)
    r"github_pat_[A-Za-z0-9_]{10,}",    # GitHub PAT (fine-grained)
    r"gho_[A-Za-z0-9]{10,}",            # GitHub OAuth access token
    r"ghu_[A-Za-z0-9]{10,}",            # GitHub user-to-server token
    r"ghs_[A-Za-z0-9]{10,}",            # GitHub server-to-server token
    r"xox[baprs]-[A-Za-z0-9-]{10,}",    # Slack tokens
    r"AIza[A-Za-z0-9_-]{30,}",          # Google API keys
    r"AKIA[A-Z0-9]{16}",                # AWS Access Key ID
    r"sk_live_[A-Za-z0-9]{10,}",        # Stripe secret key (live)
    r"sk_test_[A-Za-z0-9]{10,}",        # Stripe secret key (test)
    r"SG\.[A-Za-z0-9_-]{10,}",          # SendGrid API key
    r"hf_[A-Za-z0-9]{10,}",             # HuggingFace token
    r"npm_[A-Za-z0-9]{10,}",            # npm access token
    r"pypi-[A-Za-z0-9_-]{10,}",         # PyPI API token
]
_PREFIX_RE = re.compile(
    r"(?<![A-Za-z0-9_-])(" + "|".join(_PREFIX_PATTERNS) + r")(?![A-Za-z0-9_-])"
)

# ENV assignment patterns: KEY=value where KEY looks secret-like. Skipped for
# code_file=True since MAX_TOKENS=100 / similar constants are common and not
# secrets.
_SECRET_ENV_NAMES = r"(?:API_?KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|AUTH)"
_ENV_ASSIGN_RE = re.compile(
    rf"([A-Z0-9_]{{0,50}}{_SECRET_ENV_NAMES}[A-Z0-9_]{{0,50}})\s*=\s*(['\"]?)(\S+)\2",
)

# JSON fields: "apiKey": "value", "token": "value", etc.
_JSON_KEY_NAMES = r"(?:api_?[Kk]ey|token|secret|password|access_token|refresh_token|auth_token|bearer)"
_JSON_FIELD_RE = re.compile(rf'("{_JSON_KEY_NAMES}")\s*:\s*"([^"]+)"', re.IGNORECASE)

# Authorization headers (any scheme) and the bare-credential form.
_AUTH_HEADER_RE = re.compile(
    r"((?:Proxy-)?Authorization:\s*)([A-Za-z][\w.+-]*\s+)?([^\s\"']+)",
    re.IGNORECASE,
)

# Private key blocks.
_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN[A-Z ]*PRIVATE KEY-----[\s\S]*?-----END[A-Z ]*PRIVATE KEY-----"
)

# Database connection strings: protocol://user:PASSWORD@host
_DB_CONNSTR_RE = re.compile(
    r"((?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp)://[^:\s]+:)([^@\s]+)(@)",
    re.IGNORECASE,
)

# JWT tokens: header.payload[.signature], always start with "eyJ".
_JWT_RE = re.compile(r"eyJ[A-Za-z0-9_-]{10,}(?:\.[A-Za-z0-9_=-]{4,}){0,2}")


def _mask_token(token: str) -> str:
    """Mask a token, preserving the first 6 / last 4 chars for debuggability."""
    if not token:
        return "***"
    if len(token) < 18:
        return "***"
    return f"{token[:6]}...{token[-4:]}"


def redact_sensitive_text(text: str, *, code_file: bool = False) -> str:
    """Mask secrets in ``text``. Safe on any string; non-matches pass through.

    ``code_file=True`` skips the ENV-assignment and JSON-field passes, which
    are prone to false positives on source/config content (``MAX_TOKENS=100``,
    ``"apiKey": "test"`` fixtures). Prefix-matched keys, auth headers, private
    keys, DB connection strings, and JWTs are still redacted either way.
    """
    if not text or not _REDACT_ENABLED:
        return text

    if _PREFIX_RE.search(text):
        text = _PREFIX_RE.sub(lambda m: _mask_token(m.group(1)), text)

    if not code_file:
        if "=" in text:
            text = _ENV_ASSIGN_RE.sub(
                lambda m: f"{m.group(1)}={m.group(2)}{_mask_token(m.group(3))}{m.group(2)}",
                text,
            )
        if ":" in text and '"' in text:
            text = _JSON_FIELD_RE.sub(
                lambda m: f'{m.group(1)}: "{_mask_token(m.group(2))}"', text
            )

    if "uthorization" in text or "UTHORIZATION" in text:
        text = _AUTH_HEADER_RE.sub(
            lambda m: m.group(1) + (m.group(2) or "") + _mask_token(m.group(3)),
            text,
        )

    if "BEGIN" in text and "-----" in text:
        text = _PRIVATE_KEY_RE.sub("[REDACTED PRIVATE KEY]", text)

    if "://" in text:
        text = _DB_CONNSTR_RE.sub(lambda m: f"{m.group(1)}***{m.group(3)}", text)

    if "eyJ" in text:
        text = _JWT_RE.sub(lambda m: _mask_token(m.group(0)), text)

    return text


# Commands whose stdout is an environment-variable dump (KEY=value lines),
# not source code -- these need the ENV-assignment pass to catch opaque
# tokens with no recognized vendor prefix.
_ENV_DUMP_COMMANDS = frozenset({"env", "printenv", "set", "export", "declare"})


def is_env_dump_command(command: str | None) -> bool:
    """True if ``command`` dumps environment variables to stdout.

    Checks the first token of every segment of a pipeline/sequence (``;`` /
    ``&&`` / ``||`` / ``|``). A parse failure or anything unrecognized
    returns False, which just means the (still-safe) code_file=True path
    is used instead.
    """
    if not command:
        return False
    for seg in re.split(r"[|;&]+", command):
        seg = seg.strip()
        if not seg:
            continue
        try:
            tokens = shlex.split(seg)
        except ValueError:
            tokens = seg.split()
        if tokens and tokens[0] in _ENV_DUMP_COMMANDS:
            return True
    return False


def redact_terminal_output(output: str, command: str | None = None) -> str:
    """Redact secrets from a command's stdout/stderr before it reaches the model."""
    if not output:
        return output
    return redact_sensitive_text(output, code_file=not is_env_dump_command(command))
