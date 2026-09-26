"""
mask-secrets.py — credential masking for text the scripts copy out of transcripts.

Not a command. detect-mechanical.py, scan-cross-session.py and
derive-session-scope.py load it by path (the file name is hyphenated like its
siblings) and pass every piece of transcript text they emit through
`squeeze()` or `mask()`. A transcript holds whatever went through the session —
`GH_TOKEN=… gh pr create`, a failed push echoing a tokenised remote URL, a key
pasted into a prompt — and the findings are what a retro quotes into memory
files, issues and pull requests.

`squeeze()` collapses whitespace, masks, and only then truncates. Truncating
first can cut a token below the pattern's minimum length, and its head then
ships in clear.
"""

from __future__ import annotations

import re

MARKER = "[REDACTED]"

# One named alternative per credential shape. The names are the contract with
# the tests: every alternative carries a sample there, so one added without a
# sample, or one dropped, fails the suite. Groups ending in `_keep` hold context
# that stays readable (the header name, the URL scheme); the rest is masked.
ALTERNATIVES: dict[str, str] = {
    "gitlab_pat": r"\bglpat-[A-Za-z0-9_-]{20,}",
    "github_token": r"\bgh[pousr]_[A-Za-z0-9]{20,}",
    "github_fine_grained": r"\bgithub_pat_[A-Za-z0-9_]{22,}",
    # `sk-…`, `sk-ant-api03-…`, `sk-proj-…`. A digit and a 20-character run
    # without a hyphen keep kebab-case words such as `sk-learn-compatible`
    # out; `\b` keeps `task-`/`desk-` out.
    "sk_key": r"\bsk-(?=[A-Za-z0-9_-]*\d)(?=[A-Za-z0-9_-]*[A-Za-z0-9_]{20})"
    r"[A-Za-z0-9_-]{20,}",
    "aws_access_key": r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b",
    "slack_token": r"\bxox[abposr]-[A-Za-z0-9-]{10,}",
    # The header alone would leave the key body in clear, and squeeze() puts
    # the body on the header's line. Consume through the footer, or through
    # the base64 run that follows when the text was cut before the footer.
    "pem_private_key": r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----"
    r"(?:[\s\S]*?-----END (?:[A-Z0-9]+ )*PRIVATE KEY-----|[A-Za-z0-9+/=\s]*)",
    # `Authorization: Bearer …` as a header, and as a JSON or YAML key
    # (`{"authorization":"Bearer …"}`).
    "authorization_header": r"(?P<authorization_header_keep>(?i:\bauthorization"
    r"[\"']?\s*:\s*[\"']?(?:basic|bearer|token)\s+))[^\s'\"]+",
    # GitLab's header takes any token, not only a `glpat-` one. A token has
    # twenty characters or more and a digit, which keeps a variable (`$T`) or
    # a program's identifier (`{"PRIVATE-TOKEN": token}`) readable.
    "private_token_header": r"(?P<private_token_header_keep>(?i:\bprivate-token"
    r"[\"']?\s*:\s*[\"']?))(?=[A-Za-z0-9_.-]*\d)[A-Za-z0-9_.-]{20,}",
    "jwt": r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]*",
    # `https://user:token@host` — the userinfo is masked, scheme and host stay.
    # The user may be empty (`redis://:password@host`), and the password may
    # hold an `@`: the userinfo runs to the last `@` before the path.
    "url_credentials": r"(?P<url_credentials_keep>\b[A-Za-z][A-Za-z0-9+.-]*://)"
    r"[^\s/@:'\"]*:[^\s/'\"]+(?=@)",
    # `curl -u user:password`: the password is masked, the user stays. Only
    # after `curl`, so `docker run -u 1000:1000` keeps its ids.
    "curl_user": r"(?P<curl_user_keep>\bcurl\b[^\n|;&]*?\s(?:-u|--user(?![\w-]))"
    r"[\s=]*[\"']?[^\s:'\"]*:)(?!\$)[^\s'\"]+",
    "vault_token": r"\bhv[sbr]\.[A-Za-z0-9_-]{20,}",
    "npm_token": r"\bnpm_[A-Za-z0-9]{36}\b",
    "google_api_key": r"\bAIza[0-9A-Za-z_-]{35}(?![0-9A-Za-z_-])",
    # The secret half of an AWS key pair, named by its variable or config key.
    "aws_secret_key": r"(?P<aws_secret_key_keep>(?i:\baws_secret_access_key"
    r"[\"']?\s*[=:]\s*[\"']?))[A-Za-z0-9/+=]{40}(?![A-Za-z0-9/+=])",
}

SECRET = re.compile("|".join(f"(?P<{n}>{rx})" for n, rx in ALTERNATIVES.items()))


def _replace(m: re.Match[str]) -> str:
    keep = m.groupdict().get(f"{m.lastgroup}_keep")
    return (keep or "") + MARKER


def mask(text: str) -> str:
    """`text` with every credential the patterns know replaced by MARKER."""
    return SECRET.sub(_replace, text or "")


def squeeze(text: str, limit: int) -> str:
    """Whitespace collapsed, credentials masked, then cut to `limit` chars."""
    return mask(re.sub(r"\s+", " ", text or "").strip())[:limit]
