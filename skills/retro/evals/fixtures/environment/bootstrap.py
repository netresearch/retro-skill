# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Netresearch DTT GmbH
"""Prepare the local test database; safe to repeat."""

import sqlite3
from pathlib import Path

with sqlite3.connect(Path(__file__).with_name("test.db")) as database:
    database.execute("CREATE TABLE IF NOT EXISTS prerequisites (name TEXT PRIMARY KEY)")
    database.execute("INSERT OR IGNORE INTO prerequisites VALUES ('ready')")
