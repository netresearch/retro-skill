# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Netresearch DTT GmbH

"""Environment for git calls of the tests, without the caller's repository."""

from __future__ import annotations

import os

# A git hook exports these; they choose the repository ahead of `-C` and cwd.
GIT_LOCATION_VARS = frozenset(
    {
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_COMMON_DIR",
        "GIT_INDEX_FILE",
        "GIT_OBJECT_DIRECTORY",
    }
)


def clean_git_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k not in GIT_LOCATION_VARS}
