# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Netresearch DTT GmbH

"""Exercise the shipped jq filter through its documented stdin entry point."""

import json
import subprocess
import unittest
from pathlib import Path

FILTER = (
    Path(__file__).resolve().parents[1] / "skills/retro/scripts/orca-search-refs.jq"
)


def run_filter(*values):
    return subprocess.run(
        ["jq", "-e", "-s", "-f", str(FILTER)],
        input="\n".join(json.dumps(value) for value in values),
        text=True,
        capture_output=True,
        check=False,
    )


def page(hits):
    return {
        "ok": True,
        "result": {
            "kind": "results",
            "hits": hits,
            "page": {"hasMore": False, "cursor": None},
            "truncated": {"query": False, "candidates": False, "freshness": False},
        },
    }


class OrcaSearchRefsTest(unittest.TestCase):
    def test_released_search_worker_response(self):
        # Real Orca Server 1.4.262 query over two synthetic projects with the
        # same text. Only the temporary root was normalized. Supply the CLI
        # success envelope around the captured worker's result.
        fixture = Path(__file__).parent / "fixtures/orca/search-result-1.4.262.json"
        result = json.loads(fixture.read_text(encoding="utf-8"))
        run = run_filter({"ok": True, "result": result})
        self.assertEqual(run.returncode, 0, run.stderr)
        refs = json.loads(run.stdout)
        self.assertEqual(
            [lead["sessionId"] for lead in refs["leads"]], ["synthetic-relay"]
        )
        self.assertFalse(refs["more"])
        self.assertNotIn("archive dispatch", run.stdout)

    def test_refs_only_with_paging_and_limited_coverage(self):
        hit = {
            "agent": "codex",
            "sessionId": "a",
            "source": {"presence": "present", "filePath": "/logs/a"},
            "evidence": {"snippet": "private conversation"},
            "resumeCommand": "untrusted command",
            "title": "private title",
        }
        response = page([hit, {**hit, "source": {"presence": "unverifiable"}}])
        response["result"]["page"] = {"hasMore": True, "cursor": "next"}
        response["result"]["truncated"]["candidates"] = True
        run = run_filter(response)
        self.assertEqual(run.returncode, 0, run.stderr)
        output = json.loads(run.stdout)
        self.assertTrue(output["more"])
        self.assertTrue(output["truncated"]["candidates"])
        self.assertEqual(output["cursor"], "next")
        self.assertEqual(output["leads"][0]["source"], hit["source"])
        self.assertIsNone(output["leads"][1]["source"]["filePath"])
        self.assertNotIn("private", run.stdout)
        self.assertNotIn("untrusted command", run.stdout)

    def test_available_empty_unavailable_and_stale_are_distinct(self):
        self.assertEqual(json.loads(run_filter(page([])).stdout)["leads"], [])
        unavailable = {"kind": "unavailable", "reason": "disabled"}
        output = run_filter({"ok": True, "result": unavailable})
        self.assertEqual(
            json.loads(output.stdout), {"coverage": "unavailable", "reason": "disabled"}
        )
        stale = run_filter({"ok": True, "result": {"kind": "stale-cursor"}})
        self.assertEqual(json.loads(stale.stdout), {"coverage": "stale-cursor"})

    def test_broken_responses_never_become_an_empty_page(self):
        incomplete = page([])
        del incomplete["result"]["truncated"]
        for values in (
            [],
            [{}],
            [{"ok": False}],
            [page([]), page([])],
            [incomplete],
            [page([{}])],
        ):
            with self.subTest(values=values):
                self.assertNotEqual(run_filter(*values).returncode, 0)
