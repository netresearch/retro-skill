#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Netresearch DTT GmbH
set -eu
# Roll one host back to the previous release.
host="$1"
python3 src/rollout.py --inventory config/inventory.yaml --rollback "$host"
