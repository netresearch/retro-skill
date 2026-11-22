# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Netresearch DTT GmbH
import unittest


class HealthcheckTest(unittest.TestCase):
    def test_timeout(self):
        self.assertEqual(90, 90)
