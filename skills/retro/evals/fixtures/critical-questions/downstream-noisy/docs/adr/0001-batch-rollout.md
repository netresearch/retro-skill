<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->
<!-- SPDX-FileCopyrightText: Netresearch DTT GmbH -->

# ADR 0001: roll out in batches

Status: accepted. A rollout deploys four hosts at a time, so a bad release reaches at most a third of the hosts before the health check stops it.
