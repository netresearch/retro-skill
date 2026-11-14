# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Netresearch DTT GmbH


def render(cache, page, language, content):
    if "fragment" not in cache:
        cache["fragment"] = content[page][language]
    return cache["fragment"]
