#!/usr/bin/env -S uv run --script
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Netresearch DTT GmbH
#
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///

"""Report observed time, usage and provenance without inventing missing data.

Supports Codex cumulative token_count snapshots and Claude message.usage.
The Codex shape was measured in 0.166.0-alpha.5.1; tests retain redacted snapshots.
An observed transcript span is neither active work time nor time to acceptance.
No pricing lookup, model call or source modification is performed.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

COUNTS = (
    "input_tokens",
    "cached_input_tokens",
    "cache_write_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
    "total_tokens",
)


def _time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        stamp = datetime.fromisoformat(value)
        return stamp.astimezone(UTC) if stamp.tzinfo else None
    except ValueError:
        return None


def _count(value: Any) -> int | None:
    return value if type(value) is int and value >= 0 else None


def _unknown(reason: str) -> dict[str, Any]:
    return {
        "status": "unknown",
        "basis": None,
        "reason": reason,
        "counts": dict.fromkeys(COUNTS),
        "input_includes_cached": None,
    }


def _usage(rows: list[dict[str, Any]]) -> dict[str, Any]:
    snapshots, messages = [], {}
    anonymous_usage = False
    for row in rows:
        payload = row.get("payload", {})
        if (
            row.get("type") == "event_msg"
            and isinstance(payload, dict)
            and payload.get("type") == "token_count"
        ):
            info = payload.get("info")
            total = info.get("total_token_usage") if isinstance(info, dict) else None
            if isinstance(total, dict):
                snapshots.append({key: _count(total.get(key)) for key in COUNTS})
        message = row.get("message", {})
        if row.get("type") == "assistant" and isinstance(message, dict):
            usage = message.get("usage")
            if isinstance(usage, dict):
                identity = message.get("id")
                if isinstance(identity, str) and identity:
                    # Streaming updates share the API message id. Later usage
                    # replaces the earlier snapshot; it is not another request.
                    messages[identity] = usage
                else:
                    anonymous_usage = True
    if snapshots:
        # A truncated session may start above zero: preserve the recorded total,
        # without claiming it is usage of only the visible excerpt. A reset or
        # missing final component must not silently preserve an earlier value.
        previous = {}
        for snapshot in snapshots:
            for key, value in snapshot.items():
                if value is None:
                    continue
                if key in previous and value < previous[key]:
                    return _unknown(
                        "cumulative counter decreased; scope/reset unresolved"
                    )
                previous[key] = value
        if all(value is None for value in snapshots[-1].values()):
            return _unknown("no supported values in the final cumulative snapshot")
        return {
            "status": "actual",
            "basis": "cumulative_snapshot",
            "reason": None,
            "counts": snapshots[-1],
            "input_includes_cached": True,
        }
    if anonymous_usage:
        return _unknown("message usage lacks a stable message id")
    if messages:
        mapping = {
            "input_tokens": "input_tokens",
            "output_tokens": "output_tokens",
            "cached_input_tokens": "cache_read_input_tokens",
            "cache_write_input_tokens": "cache_creation_input_tokens",
        }
        counts = dict.fromkeys(COUNTS)
        for target, source in mapping.items():
            values = [_count(message.get(source)) for message in messages.values()]
            counts[target] = sum(values) if all(v is not None for v in values) else None
        parts = [counts[key] for key in mapping]
        counts["total_tokens"] = (
            sum(parts) if all(v is not None for v in parts) else None
        )
        if all(value is None for value in counts.values()):
            return _unknown("no supported values in message usage")
        return {
            "status": "actual",
            "basis": "deduplicated_messages",
            "reason": None,
            "counts": counts,
            "input_includes_cached": False,
        }
    return _unknown("no supported usage records")


def _embedded_summary(value: Any) -> dict[str, Any]:
    """Validate retained adapter data before treating it as normalized metrics."""

    def invalid() -> None:
        raise ValueError("invalid embedded metrics summary")

    if not isinstance(value, dict) or type(value.get("schema_version")) is not int:
        invalid()
    if value["schema_version"] != 1 or any(
        not isinstance(value.get(field), dict)
        for field in ("timing", "usage", "provenance", "coverage")
    ):
        invalid()
    usage, timing = value["usage"], value["timing"]
    counts = usage.get("counts")
    if (
        usage.get("status") not in ("actual", "unknown")
        or "input_includes_cached" not in usage
        or not isinstance(counts, dict)
        or any(key not in counts for key in COUNTS)
        or any(v is not None and _count(v) is None for v in counts.values())
        or (
            usage.get("input_includes_cached") is not None
            and type(usage["input_includes_cached"]) is not bool
        )
    ):
        invalid()
    if usage["status"] == "actual" and all(v is None for v in counts.values()):
        invalid()
    if usage["status"] == "unknown" and any(v is not None for v in counts.values()):
        invalid()
    for field in ("observed_start", "observed_end"):
        if field not in timing or (
            timing[field] is not None and _time(timing[field]) is None
        ):
            invalid()
    start, end = (_time(timing[field]) for field in ("observed_start", "observed_end"))
    if (start is None) != (end is None) or (start is not None and end < start):
        invalid()
    for field in (
        "observed_span_seconds",
        "active_seconds",
        "human_wait_seconds",
        "time_to_accepted_result_seconds",
    ):
        duration = timing.get(field)
        if duration is not None and (
            type(duration) not in (int, float)
            or not math.isfinite(duration)
            or duration < 0
        ):
            invalid()
    if "session_id" not in value["provenance"] or (
        value["provenance"]["session_id"] is not None
        and not isinstance(value["provenance"]["session_id"], str)
    ):
        invalid()
    return copy.deepcopy(value)


def collect(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Normalize one transcript; unknown facts stay null, not inferred."""
    rows = [row for row in rows if isinstance(row, dict)]
    # The adapter retains this exact summary on an ordinary message event.
    embedded = [row["retro_metrics"] for row in rows if "retro_metrics" in row]
    if embedded:
        if len(embedded) != 1:
            raise ValueError("multiple embedded metrics summaries; scope unresolved")
        return _embedded_summary(embedded[0])
    stamps = [
        stamp for row in rows if (stamp := _time(row.get("timestamp"))) is not None
    ]
    start, end = (min(stamps), max(stamps)) if stamps else (None, None)
    models, runtime, version, session_id = set(), None, None, None
    for row in rows:
        payload = row.get("payload", {})
        message = row.get("message", {})
        if isinstance(payload, dict):
            if row.get("type") == "session_meta":
                runtime, version, session_id = (
                    "codex",
                    payload.get("cli_version"),
                    payload.get("id"),
                )
            if row.get("type") == "turn_context" and isinstance(
                payload.get("model"), str
            ):
                models.add(payload["model"])
        if (
            row.get("type") == "assistant"
            and isinstance(message, dict)
            and isinstance(message.get("model"), str)
        ):
            models.add(message["model"])
    return {
        "schema_version": 1,
        "timing": {
            "observed_start": start.isoformat() if start else None,
            "observed_end": end.isoformat() if end else None,
            "observed_span_seconds": (end - start).total_seconds() if start else None,
            "active_seconds": None,
            "human_wait_seconds": None,
            "time_to_accepted_result_seconds": None,
        },
        "usage": _usage(rows),
        "cost": None,
        "quality": None,
        "provenance": {
            "runtime": runtime,
            "runtime_version": version,
            "session_id": session_id,
            "execution": {
                "reported_models": sorted(models),
                "exact_model_version": None,
            },
            "retro_reviewer": None,
            "eval_executor": None,
            "eval_judge": None,
            "loaded_skills": None,
            "tool_environment": None,
            "eval_version": None,
        },
        "coverage": {
            "records_read": len(rows),
            "complete_session": None,
            "stages": {
                "task": None,
                "retro": None,
                "implementation": None,
                "verification": None,
                "delegation": None,
                "maintenance": None,
                "human_rework": None,
            },
        },
    }


def combine(reports: list[dict[str, Any]], subagent_usage: str) -> dict[str, Any]:
    """Union observed intervals; aggregate usage only with explicit containment."""
    intervals = sorted(
        (start, end)
        for report in reports
        if (start := _time(report["timing"]["observed_start"])) is not None
        and (end := _time(report["timing"]["observed_end"])) is not None
    )
    union, previous_end = 0.0, None
    for start, end in intervals:
        lower = max(start, previous_end) if previous_end else start
        union += max(0.0, (end - lower).total_seconds())
        previous_end = max(previous_end, end) if previous_end else end
    if len(reports) == 1 or subagent_usage == "included":
        usage = reports[0]["usage"]
    elif subagent_usage == "excluded":
        # Different input/cache semantics cannot safely be combined by field.
        semantics = {report["usage"]["input_includes_cached"] for report in reports}
        if len(semantics) != 1 or None in semantics:
            usage = _unknown("mixed or unknown usage semantics")
        else:
            counts = {}
            for key in COUNTS:
                values = [report["usage"]["counts"][key] for report in reports]
                counts[key] = (
                    sum(values) if all(v is not None for v in values) else None
                )
            usage = {
                "status": "actual",
                "basis": "disjoint_transcripts",
                "reason": None,
                "counts": counts,
                "input_includes_cached": semantics.pop(),
            }
    else:
        usage = _unknown("parent/subagent counter containment unknown")
    return {
        "schema_version": 1,
        "reports": reports,
        "subagent_usage": subagent_usage,
        "observed_interval_union_seconds": union if intervals else None,
        "timing_coverage": "all" if len(intervals) == len(reports) else "partial",
        "usage": usage,
        "cost": None,
        "quality": None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transcript-file", type=Path, required=True)
    parser.add_argument("--subagent-transcript", type=Path, action="append", default=[])
    parser.add_argument(
        "--subagent-usage",
        choices=("included", "excluded", "unknown"),
        default="unknown",
        help="Does the parent counter already include the supplied children?",
    )
    args = parser.parse_args()
    reports = []
    try:
        seen, digests, session_ids = set(), set(), set()
        for path in [args.transcript_file, *args.subagent_transcript]:
            identity = path.resolve()
            if identity in seen:
                raise ValueError(f"transcript supplied twice: {path}")
            seen.add(identity)
            content = path.read_bytes()
            digest = hashlib.sha256(content).hexdigest()
            if digest in digests:
                raise ValueError(f"copied transcript supplied twice: {path}")
            digests.add(digest)
            rows = [
                json.loads(line)
                for line in content.decode("utf-8").splitlines()
                if line.strip()
            ]
            if not rows or not all(isinstance(row, dict) for row in rows):
                raise ValueError(f"no transcript objects: {path}")
            report = collect(rows)
            session_id = report["provenance"]["session_id"]
            if isinstance(session_id, str) and session_id:
                if session_id in session_ids:
                    raise ValueError(f"session supplied twice: {path}")
                session_ids.add(session_id)
            report["source"] = {"path": str(path), "sha256": digest}
            reports.append(report)
    except (OSError, ValueError) as error:
        parser.exit(2, f"collect-session-metrics: {error}\n")
    output = reports[0] if len(reports) == 1 else combine(reports, args.subagent_usage)
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
