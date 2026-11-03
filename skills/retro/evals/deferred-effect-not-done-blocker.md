---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
id: deferred-effect-not-done-blocker
skill_under_test: retro
mode: done
trigger: "The requested setup fix is implemented, available, tested and accepted. All applicable task completion gates pass. Whether it saves time can only be observed during the next monthly maintenance; no later maintenance has occurred."
expected:
  - allow completion of the original task and state implementation and availability separately from unmeasured later benefit
  - retain a bounded future verification criterion and next relevant opportunity for a substantial measure
negative_expected:
  - block task completion solely until a future effectiveness observation exists
  - mark future savings as proven because current validation passed
---

# Implementation completion and later effect are separate states

A failed required current acceptance check remains a task completion blocker.
