# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Netresearch DTT GmbH

import json
from pathlib import Path


def render(cache, page, language, content):
    if page not in cache:
        cache[page] = content[page][language]
    return cache[page]


if __name__ == "__main__":
    fixture = Path(__file__).resolve().parents[1] / "content.json"
    content = json.loads(fixture.read_text(encoding="utf-8"))
    cache = {}
    print(
        json.dumps(
            [
                render(cache, "home", "en", content),
                render(cache, "about", "en", content),
            ]
        )
    )
