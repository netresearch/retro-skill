#!/bin/sh
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Netresearch DTT GmbH
set -eu
python3 "$(dirname "$0")/check.py"
