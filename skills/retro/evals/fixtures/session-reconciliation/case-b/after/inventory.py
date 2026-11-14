# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Netresearch DTT GmbH

import json
from pathlib import Path


class Client:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def get(self, path):
        self.calls.append(path)
        return self.responses[path]


def collect(client):
    names = []
    path = "/jobs?limit=2"
    while path is not None:
        response = client.get(path)
        names.extend(job["name"] for job in response["items"] if job["enabled"])
        path = response["next"]
    return sorted(names)


if __name__ == "__main__":
    fixture = Path(__file__).resolve().parents[1] / "api.json"
    client = Client(json.loads(fixture.read_text(encoding="utf-8")))
    print(json.dumps(collect(client)))
