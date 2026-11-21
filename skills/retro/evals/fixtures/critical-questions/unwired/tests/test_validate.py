# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Netresearch DTT GmbH
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from validate import validate


class ValidateTest(unittest.TestCase):
    def test_empty_email_is_rejected(self):
        self.assertEqual(validate({"email": "  "}), ["email is required"])

    def test_email_without_at_is_rejected(self):
        self.assertEqual(validate({"email": "x"}), ["email is invalid"])

    def test_valid_email_passes(self):
        self.assertEqual(validate({"email": "a@example.org"}), [])


if __name__ == "__main__":
    unittest.main()
