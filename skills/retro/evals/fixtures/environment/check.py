# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Netresearch DTT GmbH
"""Check a real prerequisite without silently creating it."""

import sqlite3
from pathlib import Path

path = Path(__file__).with_name("test.db")
with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as database:
    assert database.execute("SELECT name FROM prerequisites").fetchall() == [("ready",)]
print("Local database check passed")
