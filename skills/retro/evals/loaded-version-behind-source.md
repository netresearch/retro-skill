---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
id: loaded-version-behind-source
skill_under_test: retro
mode: sweep
fixture: fixtures/loaded-version
trigger: "The recorded loaded skill at revision a1 recommends legacy-export; that call failed. Current source main at b2 already replaces it with export-v2 and has a regression case. The session used a cache last refreshed before b2."
expected:
  - compare the actually loaded revision with current source and diagnose distribution or refresh as the observed gap
  - propose an authorized update of the installation or its refresh path rather than a duplicate source correction
  - retain uncertainty if the historical loaded content cannot actually be retrieved
negative_expected:
  - patch current source to introduce export-v2 again
  - conclude that the already corrected instruction was loaded and ineffective
---

# Loaded context and patch baseline are different evidence

A current source revision carrying the same defect would instead support a
source patch.
