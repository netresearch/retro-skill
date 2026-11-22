<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->
<!-- SPDX-FileCopyrightText: Netresearch DTT GmbH -->

# On-call

## When a rollout reports failures

The rollout prints its result with `python3 report.py`. For each failed host,
read the error printed for that host and decide:

- `disk full` or `health check timeout`: retry that host once.
- any other error: roll that host back with `rollback.sh <host>`.

The rollout keeps no log file; the printed result is the only record.
