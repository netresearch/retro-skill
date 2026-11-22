<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->
<!-- SPDX-FileCopyrightText: Netresearch DTT GmbH -->

# Architecture

`deploy.sh` calls `src/rollout.py`, which deploys each host and writes `results.json`. `report.py` reads that file and prints the result.
