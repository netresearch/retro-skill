# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Netresearch DTT GmbH

import unittest

from rendering import render


class RenderingTest(unittest.TestCase):
    def test_pages(self):
        content = {"home": {"en": "Welcome"}, "about": {"en": "About us"}}
        cache = {}
        self.assertEqual(render(cache, "home", "en", content), "Welcome")
        self.assertEqual(render(cache, "about", "en", content), "About us")

    def test_reuses_entry(self):
        content = {"home": {"en": "Welcome"}}
        cache = {}
        self.assertEqual(render(cache, "home", "en", content), "Welcome")
        content["home"]["en"] = "Updated"
        self.assertEqual(render(cache, "home", "en", content), "Welcome")


if __name__ == "__main__":
    unittest.main()
