#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Netresearch DTT GmbH

"""Unit tests for skills/retro/scripts/check-upstream-sources.py (offline paths only)."""

from __future__ import annotations

import datetime
import http.server
import importlib.util
import shutil
import tempfile
import threading
import typing
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load():
    path = REPO_ROOT / "skills" / "retro" / "scripts" / "check-upstream-sources.py"
    spec = importlib.util.spec_from_file_location("check_upstream_sources", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cus = _load()


class FixtureMixin(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        (self.dir / "references").mkdir()
        (self.dir / "SKILL.md").write_text("# Fixture skill\n")


class TestCollectMarkdown(FixtureMixin):
    def test_labelled_link_is_collected_adjacent_line_included(self):
        (self.dir / "references" / "a.md").write_text(
            "See [Foo](https://example.org/foo.html)\n"
            "`[upstream]` — canonical.\n"
            "\n"
            "Unlabelled [Bar](https://example.org/bar.html) elsewhere.\n"
        )
        urls = {o["url"] for o in cus.collect_markdown(self.dir)}
        self.assertIn("https://example.org/foo.html", urls)
        self.assertNotIn("https://example.org/bar.html", urls)

    def test_url_with_parentheses_is_kept_whole(self):
        """`[^)\\s]+` stopped at the first `)`, and the cut URL probed as 404."""
        (self.dir / "references" / "a.md").write_text(
            "[Foo](https://en.wikipedia.org/wiki/Foo_(bar)) `[upstream]`\n"
            "[Baz](https://example.org/baz) `[upstream]`\n"
        )
        urls = [o["url"] for o in cus.collect_markdown(self.dir)]
        self.assertEqual(
            urls, ["https://en.wikipedia.org/wiki/Foo_(bar)", "https://example.org/baz"]
        )

    def test_no_labels_means_no_urls(self):
        (self.dir / "references" / "a.md").write_text(
            "Only [Bar](https://example.org/bar.html), no label anywhere.\n"
        )
        self.assertEqual(cus.collect_markdown(self.dir), [])


class TestCollectCheckpoints(FixtureMixin):
    def test_source_url_and_verified_date_are_attributed_to_the_entry(self):
        (self.dir / "checkpoints.yaml").write_text(
            "mechanical:\n"
            "  - id: XX-01\n"
            "    type: file_exists\n"
            "    target: README.md\n"
            '    source: "https://example.org/spec — see note"\n'
            "    verified: 2020-01-01\n"
        )
        urls, verified = cus.collect_checkpoints(self.dir)
        self.assertEqual(urls[0]["url"], "https://example.org/spec")
        self.assertIn("XX-01", urls[0]["origin"])
        self.assertEqual(verified[0]["checkpoint"], "XX-01")
        self.assertEqual(verified[0]["date"], "2020-01-01")

    def test_checkpoint_source_with_parentheses_is_kept_whole(self):
        (self.dir / "checkpoints.yaml").write_text(
            "mechanical:\n"
            "  - id: XX-03\n"
            "    source: https://en.wikipedia.org/wiki/Foo_(bar)\n"
        )
        urls, _verified = cus.collect_checkpoints(self.dir)
        self.assertEqual(
            [u["url"] for u in urls], ["https://en.wikipedia.org/wiki/Foo_(bar)"]
        )

    def test_non_url_source_yields_no_url_occurrence(self):
        (self.dir / "checkpoints.yaml").write_text(
            "mechanical:\n"
            "  - id: XX-02\n"
            '    source: "observed in session 0815, no URL"\n'
        )
        urls, verified = cus.collect_checkpoints(self.dir)
        self.assertEqual(urls, [])
        self.assertEqual(verified, [])


class TestStaleFindings(unittest.TestCase):
    def test_old_date_flags_and_fresh_date_stays_quiet(self):
        old = {"checkpoint": "XX-01", "date": "2020-01-01", "file": "c.yaml", "line": 5}
        fresh = {
            "checkpoint": "XX-02",
            "date": datetime.datetime.now(datetime.UTC).date().isoformat(),
            "file": "c.yaml",
            "line": 9,
        }
        findings = cus.stale_findings([old, fresh], max_age_days=180)
        self.assertEqual([f["checkpoint"] for f in findings], ["XX-01"])
        self.assertEqual(findings[0]["signal"], "B14")
        self.assertEqual(findings[0]["name"], "upstream_verification_stale")

    def test_impossible_date_is_a_finding_not_a_crash(self):
        bad = {"checkpoint": "XX-03", "date": "2026-02-30", "file": "c.yaml", "line": 7}
        findings = cus.stale_findings([bad], max_age_days=180)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["name"], "upstream_verification_invalid")
        self.assertEqual(findings[0]["checkpoint"], "XX-03")


class _Redirects(http.server.BaseHTTPRequestHandler):
    """`/moved` → a login page, `/slash` → itself plus `/`, everything else 200."""

    requests: typing.ClassVar[list[str]] = []

    def _answer(self):
        _Redirects.requests.append(self.path)
        target = {"/moved": "/login?next=moved", "/slash": "/slash/"}.get(self.path)
        if target:
            self.send_response(301)
            self.send_header("Location", target)
        else:
            self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    do_HEAD = do_GET = _answer

    def log_message(self, *args):
        pass


class TestProbeRedirects(unittest.TestCase):
    def setUp(self):
        server = http.server.HTTPServer(("127.0.0.1", 0), _Redirects)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.base = f"http://127.0.0.1:{server.server_port}"
        # The default opener refuses this server (http, loopback); these tests
        # are about the redirect verdicts, so they bring a plain one.
        self.opener = urllib.request.build_opener()

    def test_redirect_to_another_path_is_reported(self):
        verdict, _status, detail = cus.probe(
            f"{self.base}/moved", timeout=5, opener=self.opener
        )
        self.assertEqual(verdict, "redirected")
        self.assertIn("/login?next=moved", detail)

    def test_trailing_slash_redirect_and_plain_page_are_ok(self):
        for path in ("/slash", "/page"):
            with self.subTest(path=path):
                self.assertEqual(
                    cus.probe(f"{self.base}{path}", timeout=5, opener=self.opener)[0],
                    "ok",
                )

    def test_redirect_becomes_its_own_finding(self):
        occurrence = {"file": "references/a.md", "line": 3, "origin": "markdown"}
        findings = cus.probe_findings(
            {f"{self.base}/moved": [occurrence]}, timeout=5, opener=self.opener
        )
        self.assertEqual([f["name"] for f in findings], ["upstream_source_redirected"])


class TestProbeTargets(unittest.TestCase):
    """Only https URLs on public addresses are requested."""

    def setUp(self):
        server = http.server.HTTPServer(("127.0.0.1", 0), _Redirects)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.port = server.server_port
        _Redirects.requests = []

    @staticmethod
    def _resolves_to(*addresses):
        def fake(host, port, *args, **kwargs):
            return [(2, 1, 6, "", (a, port)) for a in addresses]

        return mock.patch.object(cus.socket, "getaddrinfo", side_effect=fake)

    def test_http_url_is_not_requested(self):
        verdict, _status, detail = cus.probe(f"http://127.0.0.1:{self.port}/page", 5)
        self.assertEqual(verdict, "probe_failed")
        self.assertIn("only https", detail)
        self.assertEqual(_Redirects.requests, [])

    def test_loopback_https_url_is_not_connected(self):
        verdict, _status, detail = cus.probe(f"https://127.0.0.1:{self.port}/page", 5)
        self.assertEqual(verdict, "probe_failed")
        self.assertIn("not a public address", detail)
        self.assertEqual(_Redirects.requests, [])

    def test_host_with_a_non_public_address_is_refused(self):
        for addresses in (
            ("169.254.169.254",),
            ("10.0.0.7",),
            ("100.64.0.1",),
            ("::1",),
            ("::ffff:127.0.0.1",),
            ("93.184.215.14", "192.168.1.1"),
        ):
            with (
                self.subTest(addresses=addresses),
                self._resolves_to(*addresses),
                self.assertRaisesRegex(OSError, "not a public address"),
            ):
                cus._public_address("docs.example.org", 443)

    def test_host_with_public_addresses_is_connected_to_the_checked_one(self):
        with self._resolves_to("93.184.215.14", "93.184.215.15"):
            self.assertEqual(
                cus._public_address("docs.example.org", 443), "93.184.215.14"
            )

    def test_redirect_to_http_is_refused(self):
        handler = cus._HTTPSOnlyRedirects()
        request = urllib.request.Request("https://docs.example.org/a")
        with self.assertRaisesRegex(urllib.error.URLError, "non-https"):
            handler.redirect_request(
                request, None, 302, "Found", {}, "http://docs.example.org/b"
            )
        followed = handler.redirect_request(
            request, None, 302, "Found", {}, "https://docs.example.org/b"
        )
        self.assertEqual(followed.full_url, "https://docs.example.org/b")

    def test_redirect_to_a_non_public_host_is_refused(self):
        """Every connection, including one a redirect asks for, is checked."""
        opener = cus.public_https_opener()
        with (
            self._resolves_to("127.0.0.1"),
            self.assertRaisesRegex(urllib.error.URLError, "not a public address"),
        ):
            opener.open("https://docs.example.org/", timeout=5)

    def test_default_opener_does_not_use_a_proxy(self):
        handlers = cus.public_https_opener().handlers
        self.assertFalse(
            any(isinstance(h, urllib.request.ProxyHandler) for h in handlers)
        )
        self.assertFalse(
            any(isinstance(h, urllib.request.HTTPHandler) for h in handlers)
        )


class TestUrlCleanup(unittest.TestCase):
    def test_trailing_punctuation_is_stripped(self):
        self.assertEqual(
            cus._clean_url("https://example.org/x.html;"), "https://example.org/x.html"
        )


if __name__ == "__main__":
    unittest.main()
