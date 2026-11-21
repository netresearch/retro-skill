#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Netresearch DTT GmbH
set -eu
# Roll the release out in batches and write results.json.
python3 src/rollout.py --inventory config/inventory.yaml --out results.json
