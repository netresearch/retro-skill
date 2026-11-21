# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Netresearch DTT GmbH
"""Validate a signup request."""


def validate(request: dict) -> list[str]:
    errors = []
    email = request.get("email", "").strip()
    if not email:
        errors.append("email is required")
    elif "@" not in email:
        errors.append("email is invalid")
    return errors
