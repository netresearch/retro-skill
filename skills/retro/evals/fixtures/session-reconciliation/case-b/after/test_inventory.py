# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Netresearch DTT GmbH

import unittest

from inventory import Client, collect


class InventoryTest(unittest.TestCase):
    def test_enabled_jobs(self):
        client = Client(
            {
                "/jobs?limit=2": {
                    "items": [
                        {"name": "build", "enabled": True},
                        {"name": "nightly", "enabled": False},
                    ],
                    "next": None,
                }
            }
        )
        self.assertEqual(collect(client), ["build"])

    def test_empty(self):
        client = Client({"/jobs?limit=2": {"items": [], "next": None}})
        self.assertEqual(collect(client), [])

    def test_responses(self):
        client = Client(
            {
                "/jobs?limit=2": {
                    "items": [{"name": "build", "enabled": True}],
                    "next": "/jobs?cursor=2",
                },
                "/jobs?cursor=2": {
                    "items": [
                        {"name": "deploy", "enabled": True},
                        {"name": "nightly", "enabled": False},
                    ],
                    "next": None,
                },
            }
        )
        self.assertEqual(collect(client), ["build", "deploy"])


if __name__ == "__main__":
    unittest.main()
