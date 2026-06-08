#!/usr/bin/env python3
"""
extract-coach-events.py — read claude-coach events.sqlite if present.

Used as optional Schicht-C data source. Gracefully degrades when Coach is not
installed or schema differs.

Usage:
    python3 extract-coach-events.py [--since "30 days ago"] [--db PATH]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

DEFAULT_DB = Path.home() / ".claude-coach" / "events.sqlite"


def parse_since(s: str) -> datetime | None:
    if not s:
        return None
    s = s.strip()
    # Accept ISO date or relative "N days/hours ago"
    if s.endswith(" ago"):
        parts = s[:-4].split()
        if len(parts) == 2:
            try:
                n = int(parts[0])
            except ValueError:
                return None
            unit = parts[1].lower().rstrip("s")
            delta_map = {
                "day": timedelta(days=n),
                "hour": timedelta(hours=n),
                "week": timedelta(weeks=n),
                "minute": timedelta(minutes=n),
            }
            delta = delta_map.get(unit)
            return datetime.now() - delta if delta else None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--since", default="30 days ago")
    parser.add_argument("--limit", type=int, default=500)
    args = parser.parse_args()

    if not args.db.exists():
        # Graceful absence — Coach not installed
        print(json.dumps({"available": False, "reason": f"not found: {args.db}"}))
        return 0

    since = parse_since(args.since)

    try:
        conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    except sqlite3.OperationalError as e:
        print(json.dumps({"available": False, "reason": f"open failed: {e}"}))
        return 0

    try:
        # Discover schema — Coach versions may differ
        cur = conn.cursor()
        tables = [
            r[0]
            for r in cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        ]
        if "events" not in tables:
            print(
                json.dumps(
                    {"available": False, "reason": f"no events table; tables={tables}"}
                )
            )
            return 0

        # Introspect columns
        cols = [r[1] for r in cur.execute("PRAGMA table_info(events)").fetchall()]

        select_cols = ", ".join(cols)
        sql = f"SELECT {select_cols} FROM events"
        params: list = []
        ts_col = next(
            (
                c
                for c in cols
                if "time" in c.lower() or "date" in c.lower() or "ts" in c.lower()
            ),
            None,
        )
        if since and ts_col:
            sql += f" WHERE {ts_col} >= ?"
            params.append(since.isoformat())
        sql += " ORDER BY rowid DESC LIMIT ?"
        params.append(args.limit)

        rows = [dict(zip(cols, r)) for r in cur.execute(sql, params).fetchall()]

        print(
            json.dumps(
                {
                    "available": True,
                    "db": str(args.db),
                    "columns": cols,
                    "event_count": len(rows),
                    "events": rows,
                },
                indent=2,
                default=str,
                ensure_ascii=False,
            )
        )
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
