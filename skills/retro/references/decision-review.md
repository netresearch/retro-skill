<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->
<!-- SPDX-FileCopyrightText: Netresearch DTT GmbH -->

# Review a decision against its evidence

Use this procedure in Phase 2 to discover missed checks, including in a green
session, and in Check mode before the next change. Classify findings afterwards.
The input is the original request, chronological session evidence and the
artifacts it changed. A pre-pass hit or an external defect report is not needed.

## Find the decision to inspect

Read the task and the session's own problem statements before starting from
review findings. Locate material claims that an earlier limitation was removed,
a replacement preserves required behavior, or a change handles a class of cases.
Also locate observations contradicting the working explanation. For each, find
the three anchors: **required property and its source → changed implementation
→ check of that same property**. Keep turn/file references as working notes;
do not create a new permanent register or a report full of empty rows.

A passing build, a different test or a clean review does not close a claim about
behavior it did not examine. A change of mechanism alone does not establish
that the original limitation disappeared. Check what the recorded test actually
asserts, not just its exit status or the agent's description of it.

## Resolve a concrete gap

1. Select an anchor whose connection is missing or contradictory. Read the
   relevant implementation, contract and validation artifacts at the session's
   revision. Reconcile other material claims in the same way; prioritize by
   impact and disclose unread material instead of declaring the session clear.
2. Derive one discriminating input or state from the requirement that was
   available then: would the new implementation still fail for the reason the
   old approach was replaced? For a proposed broad rebuild, ask what evidence
   rules out a bounded repair. Do not invent new product requirements.
3. Inspect the relevant path or run the smallest safe counter-probe. A direct
   code contradiction can establish a defect without execution. Use disposable
   local inputs for execution; the review grants no authority to access a new
   service, mutate production or expand the task. Do not prescribe a whole
   repository audit or more tests after decisive evidence is available.
4. Keep two conclusions separate: whether the resulting artifact meets its
   requirement, and whether an appropriate check was omitted at the decision
   point. A counter-probe run by the reviewer is new evidence, not a check the
   original agent performed. Missing historical tool/subagent coverage can
   leave the second conclusion unknown even when the first is established.
5. Look for counterevidence: a changed requirement, an explicit scope limit,
   an independently supplied verification, distinct causes or a valid small
   fix. Close the claim when the evidence supports it. Otherwise report the
   specific unmet property or evidence gap, then use the B22 outcome rules.

Only now deduplicate against B9, B19 and the other signals. Preserve the
requirement, implementation evidence and missed check under whichever signal
fits. Rediscovering an already reported defect with a new label is not a
detection gain. The procedure does not prove arbitrary silent defects absent.

## Check mode during work

Use /retro check for the current decision when a fix recurs, an observation
contradicts the explanation, or a replacement is about to be declared complete
without evidence for the property it was meant to restore. Read only the
relevant task context and artifacts, perform the procedure above, and return
the property checked, concrete evidence and next justified action.

Then resume the authorized work. A small fix, a bounded structural change or
keeping the current implementation can each be correct. Apply and verify a
correction only when the ongoing task already authorizes it; a read-only review
stays read-only. A genuine decision outside the mandate goes to its owner.

Check mode is a short decision aid: no full retrospective, skill-inventory
sweep, tracker discovery, durable rule write or completion-gate report. A later
Sweep can route a reusable learning from its observed result. Invocation or
loading by the host is required; describing this mode installs no background
hook and does not demonstrate automatic invocation in another agent runtime.
