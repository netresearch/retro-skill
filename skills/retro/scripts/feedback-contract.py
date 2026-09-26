"""Validate local feedback supplied by the integration that owns a tracker.

This module performs no discovery, imports no provider code and runs no commands.
The versioned contract is documented in references/feedback-contract.md.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

MAX_FILE_BYTES = 10 * 1024 * 1024
STATUSES = frozenset({"fetched", "read_failed", "unsupported"})
AUTHOR_CLASSES = frozenset({"self", "bot", "human"})
# Unknown keys are rejected: a misspelled `truncated` would otherwise report
# an incompletely read artifact as complete.
DOCUMENT_KEYS = frozenset({"version", "artefacts"})
ARTIFACT_KEYS = frozenset(
    {
        "url",
        "status",
        "title",
        "state",
        "error",
        "self_comments",
        "truncated",
        "references",
        "findings",
    }
)
FINDING_KEYS = frozenset(
    {
        "source",
        "author",
        "author_class",
        "created_at",
        "body",
        "url",
        "resolved",
        "report",
        "path",
        "line",
        "commit_after",
        "last_self_reply",
        "last_activity",
    }
)
REFERENCE_KEYS = frozenset({"ref", "context"})
# Newlines and tabs are allowed in a finding body only; every other control
# character could forge report lines or drive the terminal.
BODY_WHITESPACE = frozenset("\n\t")


class FeedbackValidationError(ValueError):
    """A value in an external feedback document violates the input contract."""


def canonical_url(value: Any) -> str:
    """Require an absolute HTTPS identity, without credentials or a fragment."""
    if not isinstance(value, str) or any(c.isspace() or ord(c) < 32 for c in value):
        raise FeedbackValidationError("artifact URL must be an absolute HTTPS URL")
    try:
        parts = urlsplit(value)
        port = parts.port  # Validate malformed ports even for local-only evidence.
    except ValueError as exc:
        raise FeedbackValidationError("invalid artifact URL") from exc
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or "\\" in value
        or (port is not None and not 1 <= port <= 65535)
    ):
        raise FeedbackValidationError(
            "artifact URL must be HTTPS and must not contain credentials"
        )
    host = parts.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    authority = f"{host}:{port}" if port and port != 443 else host
    return urlunsplit((parts.scheme, authority, parts.path, parts.query, ""))


def finding_url(value: Any) -> str | None:
    """Validate links while preserving comment anchors (not artifact identity)."""
    if value is None:
        return None
    url = canonical_url(value)
    fragment = urlsplit(value).fragment
    return f"{url}#{fragment}" if fragment else url


def _only_keys(raw: dict[str, Any], allowed: frozenset[str], label: str) -> None:
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise FeedbackValidationError(f"{label} has unknown keys: {', '.join(unknown)}")


def _no_control(value: str, label: str, allowed: frozenset[str] = frozenset()) -> str:
    if any((ord(c) < 32 or 0x7F <= ord(c) < 0xA0) and c not in allowed for c in value):
        raise FeedbackValidationError(f"{label} must not contain control characters")
    return value


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FeedbackValidationError(f"{label} must be a non-empty string")
    return _no_control(value, label)


def _optional_text(raw: dict[str, Any], name: str, label: str) -> str | None:
    value = raw.get(name)
    if value is not None and not isinstance(value, str):
        raise FeedbackValidationError(f"{label}.{name} must be a string or null")
    return None if value is None else _no_control(value, f"{label}.{name}")


def _timestamp(value: Any, label: str) -> str:
    text = _text(value, label)
    try:
        stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise FeedbackValidationError(f"{label} must be an ISO 8601 timestamp") from exc
    if stamp.tzinfo is None:
        raise FeedbackValidationError(f"{label} must include a UTC offset")
    return text


def _finding(raw: Any, url: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise FeedbackValidationError("each finding must be an object")
    _only_keys(raw, FINDING_KEYS, "finding")
    if (
        not isinstance(raw.get("author_class"), str)
        or raw["author_class"] not in AUTHOR_CLASSES
    ):
        raise FeedbackValidationError("finding.author_class must be self, bot or human")
    if not isinstance(raw.get("body"), str):
        raise FeedbackValidationError("finding.body must be a string")
    result = {
        "artefact": url,
        "source": _text(raw.get("source"), "finding.source"),
        "author": _text(raw.get("author"), "finding.author"),
        "author_class": raw["author_class"],
        "created_at": _timestamp(raw.get("created_at"), "finding.created_at"),
        "body": _no_control(raw["body"], "finding.body", BODY_WHITESPACE),
        "report": False,
        "url": finding_url(raw.get("url")),
    }
    result.update(_optional_finding_fields(raw))
    return result


def _optional_finding_fields(raw: dict[str, Any]) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for name in ("resolved", "report"):
        if name in raw:
            if not isinstance(raw[name], bool):
                raise FeedbackValidationError(f"finding.{name} must be boolean")
            fields[name] = raw[name]
    for name in ("path", "commit_after", "last_self_reply"):
        if name in raw:
            fields[name] = _optional_text(raw, name, "finding")
    if raw.get("last_activity") is not None:
        fields["last_activity"] = _timestamp(
            raw["last_activity"], "finding.last_activity"
        )
    if "line" in raw:
        line = raw["line"]
        if line is not None and (type(line) is not int or line < 1):
            raise FeedbackValidationError(
                "finding.line must be a positive integer or null"
            )
        fields["line"] = line
    return fields


def _record(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise FeedbackValidationError("each artifact must be an object")
    _only_keys(raw, ARTIFACT_KEYS, "artifact")
    url = canonical_url(raw.get("url"))
    status = raw.get("status")
    if not isinstance(status, str) or status not in STATUSES:
        raise FeedbackValidationError(
            "artifact.status must be fetched, read_failed or unsupported"
        )
    count = raw.get("self_comments", 0)
    if type(count) is not int or count < 0:
        raise FeedbackValidationError(
            "artifact.self_comments must be a non-negative integer"
        )
    truncated = _truncated(raw.get("truncated", []))
    result = {
        "url": url,
        "status": status,
        "self_comments": count,
        "references": _bindings(raw.get("references", [])),
        "truncated": truncated,
        "linked": [],
        "tickets": [],
        "findings": [],
    }
    for name in ("title", "state"):
        result[name] = _optional_text(raw, name, "artifact")
    return _with_evidence(raw, result)


def _truncated(value: Any) -> list[str]:
    if not isinstance(value, list):
        raise FeedbackValidationError("artifact.truncated must be a list of strings")
    return [_text(x, "artifact.truncated entry") for x in value]


def _with_evidence(raw: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """An unread artifact carries an error; a fetched one a findings list."""
    url, truncated = result["url"], result["truncated"]
    if result["status"] != "fetched":
        result["error"] = _text(raw.get("error"), "artifact.error")
        if ("findings" in raw and raw["findings"] != []) or truncated:
            raise FeedbackValidationError(
                "unread artifacts cannot claim findings or pagination coverage"
            )
        return result
    if "error" in raw:
        raise FeedbackValidationError("a fetched artifact must not contain an error")
    findings = raw.get("findings")
    if not isinstance(findings, list):
        raise FeedbackValidationError(
            "a fetched artifact must explicitly supply a findings list"
        )
    for entry in findings:
        item = _finding(entry, url)
        if item["author_class"] == "self":
            result["self_comments"] += 1
        else:
            result["findings"].append(item)
    return result


def _bindings(references: Any) -> list[dict[str, str]]:
    if not isinstance(references, list):
        raise FeedbackValidationError("artifact.references must be a list")
    bindings = []
    for ref in references:
        if not isinstance(ref, dict):
            raise FeedbackValidationError("each reference must be an object")
        _only_keys(ref, REFERENCE_KEYS, "reference")
        bindings.append(
            {
                "ref": _text(ref.get("ref"), "reference.ref"),
                "context": _text(ref.get("context"), "reference.context"),
            }
        )
    return bindings


def parse_document(data: Any) -> dict[str, dict]:
    """Normalize one document; preserve identity and reject ambiguous bindings."""
    if (
        not isinstance(data, dict)
        or type(data.get("version")) is not int
        or data["version"] != 1
    ):
        raise FeedbackValidationError("feedback requires integer version: 1")
    _only_keys(data, DOCUMENT_KEYS, "feedback")
    if not isinstance(data.get("artefacts"), list):
        raise FeedbackValidationError("feedback.artefacts must be a list")
    return _index([_record(raw) for raw in data["artefacts"]])


def _index(records: list[dict]) -> dict[str, dict]:
    artefacts: dict[str, dict] = {}
    references: dict[tuple[str, str], str] = {}
    for record in records:
        url = record["url"]
        if url in artefacts:
            raise FeedbackValidationError(f"duplicate feedback artifact: {url}")
        artefacts[url] = record
        for ref in record["references"]:
            key = (ref["ref"], ref["context"])
            if key in references and references[key] != url:
                raise FeedbackValidationError(f"conflicting reference binding: {key!r}")
            references[key] = url
    return {"artefacts": artefacts, "references": references}


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise FeedbackValidationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_files(paths: list[Path]) -> dict[str, dict]:
    """Read bounded local JSON files before any provider is contacted."""
    records = []
    for path in paths:
        try:
            with path.open("rb") as stream:
                content = stream.read(MAX_FILE_BYTES + 1)
            if len(content) > MAX_FILE_BYTES:
                raise FeedbackValidationError(
                    f"feedback exceeds {MAX_FILE_BYTES} bytes"
                )
            data = json.loads(content, object_pairs_hook=_unique_keys)
            records.extend(parse_document(data)["artefacts"].values())
        except (OSError, ValueError, RecursionError) as exc:
            raise FeedbackValidationError(f"{path}: {exc}") from exc
    return _index(records)
