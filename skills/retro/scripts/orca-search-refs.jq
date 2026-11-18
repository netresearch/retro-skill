# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Netresearch DTT GmbH
#
# jq -e -s -f orca-search-refs.jq. A failed/empty pipe is a coverage gap.
# Project only the fields needed to find the original. Untrusted titles,
# snippets, resume commands and extra envelope fields stay out of the report.
def locator:
  if (.sessionId | type) == "string" and (.sessionId | length) > 0
     and (.agent | type) == "string"
     and (.source.presence | IN("present", "missing", "unverifiable"))
  then {agent, sessionId, executionHostId, accountHome, accountWslDistro,
        source: (.source | {presence, filePath})}
  else error("unrecognized Orca session reference") end;

if length != 1 or .[0].ok != true then error("missing successful Orca response")
else .[0].result end
| if .kind == "results" and (.hits | type) == "array"
     and (.page.hasMore | type) == "boolean"
     and (.truncated.candidates | type) == "boolean"
     and (.truncated.query | type) == "boolean"
     and (.truncated.freshness | type) == "boolean"
  then {coverage: "indexed-conversation-page",
        more: .page.hasMore, cursor: .page.cursor,
        truncated: (.truncated | {candidates, query, freshness}),
        leads: [.hits[] | locator]}
  elif .kind == "unavailable" then {coverage: "unavailable", reason}
  elif .kind == "stale-cursor" then {coverage: "stale-cursor"}
  else error("unrecognized Orca search result") end
