<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->
<!-- SPDX-FileCopyrightText: Netresearch DTT GmbH -->

# Restore the reporting database

Authority: Data Operations; current tested procedure for this service.

1. Restore the full snapshot.
2. Replay the write-ahead log up to the agreed restore point.
3. Run the consistency checker before enabling clients.
