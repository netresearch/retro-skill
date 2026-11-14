# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Netresearch DTT GmbH


def collect(table):
    return sorted(
        line.split()[0] for line in table.splitlines()[1:] if line.endswith(" enabled")
    )
