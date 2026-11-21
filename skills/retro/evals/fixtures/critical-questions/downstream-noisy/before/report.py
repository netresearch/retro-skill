# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Netresearch DTT GmbH
"""Print the rollout result: one line per failed host with its error."""

import json
import sys
from pathlib import Path


def main(path: str = "results.json") -> int:
    hosts = json.loads(Path(path).read_text(encoding="utf-8"))["hosts"]
    for host in hosts:
        status = "ok" if host["ok"] else f"FAILED: {host['error']}"
        print(f"{host['name']}: {status}")
    return 0 if all(h["ok"] for h in hosts) else 1


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
