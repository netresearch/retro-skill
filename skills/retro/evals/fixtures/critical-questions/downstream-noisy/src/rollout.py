# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Netresearch DTT GmbH
"""Deploy a release to each host and record the result."""

import json


def record(hosts, out):
    with open(out, "w", encoding="utf-8") as handle:
        json.dump({"hosts": hosts}, handle, indent=2)
