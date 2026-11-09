# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Netresearch DTT GmbH

"""
mask-secrets.py — credential masking for text the scripts copy out of transcripts.

Not a command. detect-mechanical.py, scan-cross-session.py,
derive-session-scope.py, collect-review-findings.py and scan-memory-inventory.py
load it by path (the file name is hyphenated like its siblings) and pass every
piece of transcript, forge or note text they emit through `squeeze()` or
`mask()`. A transcript holds whatever went through the session —
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
    # GitLab's other prefixed tokens: deploy, runner, pipeline trigger, feed,
    # CI build, incoming mail, SCIM/OAuth, agent.
    "gitlab_other_token": r"\bgl(?:dt|rt|ptt|ft|cbt|imt|soat|agent)-[A-Za-z0-9_-]{20,}",
    "huggingface_token": r"\bhf_[A-Za-z0-9]{30,}",
    # Stripe secret and restricted keys; the publishable `pk_` key is public.
    "stripe_key": r"\b[rs]k_(?:live|test)_[A-Za-z0-9]{16,}",
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
    # `X-API-Key`, a vendor's `X-<Vendor>-API-Key` (`X-Redmine-API-Key`), the
    # bare `Api-Key` and `X-Auth-Token`. The colon after the name is required,
    # so the words "API key" or "auth token" in prose stay readable.
    "api_key_header": r"(?P<api_key_header_keep>(?i:\b(?:x-(?:[a-z0-9]+-)*api-?key"
    r"|api-key|x-auth-token)[\"']?\s*:\s*[\"']?))(?!\$)[^\s'\"]+",
    # The whole cookie list: `Cookie: a=1; b=2` masks both values.
    "cookie_header": r"(?P<cookie_header_keep>(?i:\b(?:set-)?cookie[\"']?\s*:\s*[\"']?))"
    r"(?!\$)[^\s'\";]+(?:;\s*[^\s'\";]+)*",
    # A credential passed in a query string; `key=` is Redmine's and Google's
    # name for the API key (`/issues.json?key=…`). Only after `?` or `&`, so
    # `monkey=` or a `key=value` pair in prose stays readable.
    "query_credential": r"(?P<query_credential_keep>[?&](?i:access_token|private_token"
    r"|api_key|apikey|token|password|client_secret|key)=)(?!\$)[^\s&#'\"]+",
    "jwt": r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]*",
    # `https://user:token@host` — the userinfo is masked, scheme and host stay.
    # The user may be empty (`redis://:password@host`), and the password may
    # hold an `@`: the userinfo runs to the last `@` before the path.
    "url_credentials": r"(?P<url_credentials_keep>\b[A-Za-z][A-Za-z0-9+.-]*://)"
    r"[^\s/@:'\"]*:[^\s/'\"]+(?=@)",
    "vault_token": r"\bhv[sbr]\.[A-Za-z0-9_-]{20,}",
    "npm_token": r"\bnpm_[A-Za-z0-9]{36}\b",
    "google_api_key": r"\bAIza[0-9A-Za-z_-]{35}(?![0-9A-Za-z_-])",
    # The secret half of an AWS key pair, named by its variable or config key.
    "aws_secret_key": r"(?P<aws_secret_key_keep>(?i:\baws_secret_access_key"
    r"[\"']?\s*[=:]\s*[\"']?))[A-Za-z0-9/+=]{40}(?![A-Za-z0-9/+=])",
}

SECRET = re.compile("|".join(f"(?P<{n}>{rx})" for n, rx in ALTERNATIVES.items()))

# `curl -u user:password`: the password is masked, the user stays; only inside
# a curl command, so `docker run -u 1000:1000` keeps its ids. This cannot be an
# alternative above: it would have to consume `curl … -u` as readable context,
# and every other secret in that span (`-H "Authorization: Bearer …"`, a
# credentialed URL) would then ship in clear, as would a second `-u`. So it is
# a pass of its own over each curl command, after the alternatives have run.
CURL_COMMAND = re.compile(r"\bcurl\b[^\n|;&]*")
# One optional `=` or whitespace run after the option, not `[\s=]*`: that and
# the user part `[^\s:'"]*` both match `=`, so a long run of `=` without a
# `:` backtracked quadratically (Sonar S8786). The separator stays optional,
# since curl also takes `-ualice:pw`.
CURL_USER_OPTION = re.compile(
    r"(?P<keep>(?<!\S)(?:-u|--user(?![\w-]))(?:=|\s+)?[\"']?[^\s:'\"]*:)"
    r"(?!\$)[^\s'\"]+"
)


# `PASSWORD=…`, `export API_TOKEN=…`, `PGPASSWORD=…`, `--db-password=…`: a
# value assigned to a name ending in a secret word. `==` and `===` are
# comparisons, not assignments. A pass of its own, after the alternatives, for
# the same reason as the curl pass: as an alternative it would start at the
# name and take the match from the shape-specific alternative behind it
# (`GH_TOKEN=ghp_…`). A value that is a variable (`$X`) or already masked
# stays as it is; `PWD` is the working directory, not a password.
SECRET_ASSIGNMENT = re.compile(
    r"(?P<keep>(?<![A-Za-z0-9_])[A-Za-z0-9_]*?"
    r"(?i:password|passwd|secret|token|api_?key|access_key|private_key)"
    r"\s*=(?!=)\s*[\"']?)(?!\$)(?!\[REDACTED\])"
    # A quoted value runs to its closing quote, spaces included; an unquoted
    # one, or a quoted one cut before its closing quote, to the next space.
    # A quote followed by a space closes an argument rather than opening a
    # value (`"token=" --flag "x"`).
    r"(?:(?<=')(?!\s)[^'\n]+(?=')|(?<=\")(?!\s)[^\"\n]+(?=\")|[^\s'\"]+)"
)


def _mask_curl_users(command: re.Match[str]) -> str:
    return CURL_USER_OPTION.sub(lambda m: m["keep"] + MARKER, command.group(0))


def _replace(m: re.Match[str]) -> str:
    keep = m.groupdict().get(f"{m.lastgroup}_keep")
    return (keep or "") + MARKER


def mask(text: str) -> str:
    """`text` with every credential the patterns know replaced by MARKER."""
    masked = CURL_COMMAND.sub(_mask_curl_users, SECRET.sub(_replace, text or ""))
    return SECRET_ASSIGNMENT.sub(lambda m: m["keep"] + MARKER, masked)


def squeeze(text: str, limit: int) -> str:
    """Whitespace collapsed, credentials masked, then cut to `limit` chars."""
    return mask(re.sub(r"\s+", " ", text or "").strip())[:limit]
