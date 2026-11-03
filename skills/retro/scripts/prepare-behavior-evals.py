#!/usr/bin/env -S uv run --script
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Netresearch DTT GmbH
#
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///

"""Prepare execution-only cases and private grading inputs; never call a model.

The generated shared/evals.json adapts retro's existing Markdown corpus to
skill-repo-skill/scripts/run-ab-evals.sh (expectations path). That runner only
tests text decisions; native tool-enabled runs consume execution/ instead.
An optional baseline directory freezes a second context for the same cases.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import shutil
from pathlib import Path


def load_validator():
    source = Path(__file__).with_name("validate-evals.py")
    spec = importlib.util.spec_from_file_location("retro_eval_validator", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


validator = load_validator()


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot(skill_dir: Path, references: list[str]) -> tuple[str, list[dict]]:
    """Freeze only explicitly selected execution instructions, never evals."""
    root = skill_dir.resolve()
    parts = []
    sources = []
    for relative in ["SKILL.md", *references]:
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError(f"Missing or out-of-root context file: {relative}")
        if path.is_relative_to(root / "evals"):
            raise ValueError("Eval answers must not enter execution context")
        parts.append(f"<!-- source: {relative} -->\n{path.read_text(encoding='utf-8')}")
        sources.append({"path": relative, "sha256": digest(path)})
    return "\n\n".join(parts), sources


def write_json(path: Path, value: object, output_root: Path) -> None:
    path = path.resolve()
    if not path.is_relative_to(output_root.resolve()):
        raise ValueError("JSON output must remain within the new run directory")
    content = json.dumps(value, indent=2, ensure_ascii=False) + "\n"
    # S8707: this path is canonically confined above to the newly created,
    # caller-selected run directory. No existing destination is reused.
    path.write_text(content, encoding="utf-8")  # NOSONAR


def prepare(args: argparse.Namespace) -> dict:
    root = args.skill_dir.resolve()
    evals = root / "evals"
    problems = validator.validate(evals, min_scenarios=1)
    if problems:
        raise ValueError("; ".join(problems))
    selected = {name.removesuffix(".md") for name in args.case}
    paths = [
        p for p in validator._scenario_files(evals) if args.all or p.stem in selected
    ]
    missing = selected - {p.stem for p in paths}
    if missing:
        raise ValueError(f"Unknown cases: {', '.join(sorted(missing))}")
    contexts = {"candidate": snapshot(root, args.reference + args.candidate_reference)}
    if args.baseline_dir:
        contexts["baseline"] = snapshot(args.baseline_dir, args.reference)
    # Refuse reuse: stale answers or artifacts must never leak into another run.
    out = args.output_dir.resolve()
    if out.exists():
        raise ValueError(f"Output directory already exists: {out}")
    out.mkdir(parents=True)
    for directory in ("execution", "grading", "shared"):
        (out / directory).mkdir()
    manifest = {
        "schema_version": 1,
        "status": "prepared_not_executed",
        "adapter_sha256": digest(Path(__file__)),
        "target": {
            "label": args.target_label,
            "execution_model": args.model,
            "resolved_model_version": args.model_version,
            "review_model": args.review_model,
            "judge_model": args.judge_model,
            "runtime": args.runtime,
            "reasoning_budget": args.reasoning_budget,
            "tool_environment": args.tool_environment,
            "samples_per_arm": args.samples,
        },
        "contexts": {},
        "cases": [],
        "shared_runner": {
            "executes_tools": False,
            "model_configuration": "Read effective models from the selected runner's result provenance; preparation does not configure that runner.",
        },
    }
    for arm, (text, sources) in contexts.items():
        path = out / "execution" / f"{arm}-context.md"
        path.write_text(text + "\n", encoding="utf-8")
        manifest["contexts"][arm] = {"sha256": digest(path), "sources": sources}
    shared = []
    for path in paths:
        fm = validator.parse_frontmatter(path.read_text(encoding="utf-8"))
        name = fm["id"]
        prompt = str(fm["trigger"]) + "\n"
        case_dir = out / "execution" / name
        case_dir.mkdir()
        fixture = fm.get("fixture")
        if fixture:
            source = (evals / str(fixture)).resolve()
            if not source.is_relative_to(evals.resolve()) or not source.is_dir():
                raise ValueError(f"Invalid fixture directory: {fixture}")
            if any(p.is_symlink() for p in source.rglob("*")):
                raise ValueError(f"Fixture symlinks are not supported: {fixture}")
            shutil.copytree(source, case_dir / "inputs")
            prompt += "\nRaw local artifacts are in inputs/. Inspect them for tool-enabled runs.\n"
        (case_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
        baseline_case = None
        if args.baseline_dir:
            baseline_case = out / "execution" / "baseline-cases" / name
            shutil.copytree(case_dir, baseline_case)
        expected = list(fm["expected"])
        negative = list(fm["negative_expected"])
        write_json(
            out / "grading" / f"{name}.json",
            {
                "id": name,
                "expected": expected,
                "negative_expected": negative,
                "source_sha256": digest(path),
            },
            out,
        )
        # Only prompt reaches the executor in the shared runner. Expectations
        # are read by its separate judge, not appended to either execution arm.
        shared.append(
            {
                "name": name,
                "prompt": str(fm["trigger"]),
                "expectations": expected + [f"Must not: {x}" for x in negative],
            }
        )
        manifest["cases"].append(
            {
                "id": name,
                "source_sha256": digest(path),
                "fixture": fixture,
                "candidate_path": str(case_dir.relative_to(out)),
                "baseline_path": str(baseline_case.relative_to(out))
                if baseline_case
                else None,
                "inputs": [
                    {"path": str(p.relative_to(case_dir)), "sha256": digest(p)}
                    for p in sorted(case_dir.rglob("*"))
                    if p.is_file()
                ],
            }
        )
    write_json(
        out / "shared" / "evals.json", {"skill_name": "retro", "evals": shared}, out
    )
    write_json(out / "manifest.json", manifest, out)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skill-dir", type=Path, default=Path(__file__).resolve().parent.parent
    )
    parser.add_argument("--baseline-dir", type=Path)
    parser.add_argument(
        "--reference",
        action="append",
        default=[],
        help="Relative context file; required in both arms",
    )
    parser.add_argument(
        "--candidate-reference",
        action="append",
        default=[],
        help="Explicit candidate-only context, e.g. a newly added reference",
    )
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--case", action="append", default=[])
    selection.add_argument("--all", action="store_true")
    parser.add_argument(
        "--output-dir", type=Path, required=True, help="New isolated run directory"
    )
    parser.add_argument("--target-label", required=True)
    parser.add_argument(
        "--model", required=True, help="Actual intended model or unresolved alias"
    )
    parser.add_argument("--model-version", default=None)
    parser.add_argument("--review-model", default=None)
    parser.add_argument("--judge-model", default=None)
    parser.add_argument("--runtime", required=True)
    parser.add_argument("--reasoning-budget", default=None)
    parser.add_argument("--tool-environment", default=None)
    parser.add_argument("--samples", type=int, default=3)
    args = parser.parse_args()
    if args.samples < 1:
        parser.error("--samples must be positive")
    try:
        manifest = prepare(args)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(f"Prepared {len(manifest['cases'])} cases; no model or grader executed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
