---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
id: opencode-chat-quote-replies-rendered
skill_under_test: retro
mode: sweep
trigger: "A /retro runs in OpenChamber. The session's owner messages include replies written to a selected fragment of an earlier message; opencode-transcript.py renders the session for the pre-pass."
expected:
  - the rendered transcript contains the quote replies as user messages (OpenChamber stores them as `synthetic` rows with `metadata.openchamberContext.kind == "chat-quote"`)
  - the mechanical pass counts them as user messages, so owner corrections inside them reach the user-correction signals
  - synthetic rows without `chat-quote` are still not rendered
negative_expected:
  - the adapter drops the quote replies as injected by opencode, silently lowering `user_messages`
  - the adapter renders every synthetic row, including harness-injected ones
---

# Scenario: OpenChamber quote replies are owner messages

A Lead session measured on 2026-11-26: 59 of 98 owner messages were quote
replies. With them dropped, the detector reported 42 user messages and the
enrichment had to work from its memory of the conversation.
