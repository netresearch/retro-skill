---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
id: situational-check-fix-is-the-evidence
skill_under_test: retro
mode: sweep
trigger: "Session log: an import failed with 'unknown delimiter' for a semicolon file, and the agent added ';' to the delimiter list in detect_delimiter(). A tab-separated file then failed with the same error. The agent replaced the fixed list in detect_delimiter() with csv.Sniffer over the file's first lines, wrote no comment about the change, and ran no separate read or test of detect_delimiter(). The complete tool log shows the edit and a later successful import of a pipe-separated file. Review the session."
expected:
  - identify the tab-separated failure as the warning sign that the fix handled one example, not the shared property
  - treat the replacement of the fixed list as handling the shared property, so the check counts as performed and there is no B22 finding
  - name the edit of detect_delimiter() as the evidence, without requiring a written note or a separate test
negative_expected:
  - report an omitted check because no read, test or explanation of detect_delimiter() appears beside the edit
  - credit the check to the first fix that only added ';'
---

# Scenario: the fix is the evidence of the check

A returning failure class is a warning sign. The second edit answers it by
handling the property both cases share, any delimiter, instead of the next
example. That edit is the check; a separate paragraph or test is not required.
Contrast `situational-check-claimed-not-performed`, where a sentence claims the
check and no edit or read shows it.

Grade the evidence and diagnosis, regardless of the signal identifier used.
