#!/usr/bin/env bash
# Extracts Acceptance Criteria (AC-n) from any supported plan artifact:
#   1. flow-bug.md        (`## Acceptance` bullet list)
#   2. PLAN.md            (`- **AC-n...:**` in §3 or `- **Acceptance:**` nested checklists in §4, optionally filtered by step/slice/story)
#   3. regression-plan.md (Markdown table rows containing `AC-n`)
# Usage: extract-acceptance.sh <plan-file> [step-or-slice-id]
set -euo pipefail

file="${1:?usage: extract-acceptance.sh <plan-file> [step-id]}"
step_filter="${2:-}"
[ -f "$file" ] || { echo "no such file: $file" >&2; exit 1; }

awk -v filter="$step_filter" '
  # Optional step/slice/story filter (e.g., "step-01", "slice-01", "Story 01")
  /^###+ / {
    if (filter != "" && tolower($0) ~ tolower(filter)) { in_filter = 1 }
    else if (filter != "") { in_filter = 0 }
  }
  filter != "" && !in_filter { next }

  # Case 1: `## Acceptance` section (flow-bug.md)
  /^## +Acceptance/ { mode = "section"; next }
  mode == "section" && /^## / { mode = ""; next }
  mode == "section" && /^- / {
    n++; sub(/^- /, ""); printf "AC-%02d  %s\n", n, $0; next
  }

  # Case 2: `- **Acceptance:**` block inside a Step (PLAN.md §4)
  /^- \*\*Acceptance:?\*\*:?/ { mode = "sublist"; next }
  mode == "sublist" && /^(- \*\*|^#|^[[:space:]]*$)/ { mode = "" }
  mode == "sublist" && /^[[:space:]]+- (\[[ xX]\] )?/ {
    n++
    line = $0
    sub(/^[[:space:]]+- (\[[ xX]\] )?/, "", line)
    printf "AC-%02d  %s\n", n, line
    next
  }

  # Case 3: Inline `- **AC-1 ...:**` or `- **AC-1 ...**:` bullets (PLAN.md §3)
  /^- \*\*AC-[0-9]+[^*]*\*\*:?/ {
    n++
    line = $0
    sub(/^- \*\*/, "", line)
    sub(/:\*\*[[:space:]]*/, ": ", line)
    sub(/\*\*:[[:space:]]*/, ": ", line)
    printf "AC-%02d  %s\n", n, line
    next
  }

  # Case 4: Regression Matrix table row `| **Tier ...** | AC-01: ... |` (regression-plan.md)
  /^\|.*AC-[0-9]+/ {
    n++
    split($0, cols, "|")
    gsub(/^[[:space:]]+|[[:space:]]+$/, "", cols[3])
    gsub(/^[[:space:]]+|[[:space:]]+$/, "", cols[6])
    printf "AC-%02d  %s — %s\n", n, cols[3], cols[6]
    next
  }
' "$file"
