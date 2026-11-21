# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Netresearch DTT GmbH
"""Print the rollout result as one summary line."""

import json
import sys
from pathlib import Path


def main(path: str = "results.json") -> int:
    hosts = json.loads(Path(path).read_text(encoding="utf-8"))["hosts"]
    failed = [h for h in hosts if not h["ok"]]
    print(f"{len(failed)} of {len(hosts)} hosts failed")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
