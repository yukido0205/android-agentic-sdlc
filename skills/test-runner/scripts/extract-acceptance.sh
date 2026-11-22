#!/usr/bin/env bash
# Extracts Acceptance Criteria (AC-n) from any supported plan artifact:
#   1. flow-bug.md        (`## Acceptance` bullet list)
#   2. PLAN.md (dense)    (§3 Story table `| Story NN | ... | AC-n | Slice |` and §4 Step table `| step-NN | Scope | Key AC | ... |`)
#   3. PLAN.md (legacy)   (`- **AC-n...:**` in §3 or `- **Acceptance:**` nested checklists in §4)
#   4. regression-plan.md (Markdown table rows containing `AC-n`)
# Usage: extract-acceptance.sh <plan-file> [step-or-slice-or-story-id]
set -euo pipefail

file="${1:?usage: extract-acceptance.sh <plan-file> [step-id]}"
step_filter="${2:-}"
[ -f "$file" ] || { echo "no such file: $file" >&2; exit 1; }

awk -v filter="$step_filter" '
  function trim(s) {
    gsub(/^[[:space:]]+|[[:space:]]+$/, "", s)
    return s
  }

  # Optional step/slice/story heading filter (e.g., "step-01", "slice-01", "Story 01")
  /^###+ / {
    if (filter != "" && tolower($0) ~ tolower(filter)) { in_filter = 1 }
    else if (filter != "") { in_filter = 0 }
  }

  # Case A: Dense PLAN.md §4 Step table row `| step-01 | Scope | Key Acceptance | Status | MR |`
  /^\|[[:space:]]*step-[0-9]+[[:space:]]*\|/ {
    split($0, cols, "|")
    step_id = trim(cols[2])
    ac_text = trim(cols[4])
    if (filter == "" || in_filter || tolower(step_id) ~ tolower(filter)) {
      if (ac_text != "" && ac_text !~ /^-+$/) {
        n++
        printf "AC-%02d  [%s] %s\n", n, step_id, ac_text
      }
    }
    next
  }

  # Case B: Dense PLAN.md §3 Story table row `| Story 01 | Capability | AC-1...; AC-2... | slice-01 |`
  /^\|[[:space:]]*Story[[:space:]]+[0-9]+[[:space:]]*\|/ {
    split($0, cols, "|")
    story_id = trim(cols[2])
    ac_cell  = trim(cols[4])
    slice_id = trim(cols[5])
    if (filter == "" || tolower(story_id) ~ tolower(filter) || tolower(slice_id) ~ tolower(filter)) {
      count = split(ac_cell, items, ";")
      for (i = 1; i <= count; i++) {
        item = trim(items[i])
        gsub(/\*\*/, "", item)
        if (item != "") {
          n++
          printf "AC-%02d  [%s] %s\n", n, story_id, item
        }
      }
    }
    next
  }

  filter != "" && !in_filter { next }

  # Case 1: `## Acceptance` section (flow-bug.md)
  /^## +Acceptance/ { mode = "section"; next }
  mode == "section" && /^## / { mode = ""; next }
  mode == "section" && /^- / {
    n++; sub(/^- /, ""); printf "AC-%02d  %s\n", n, $0; next
  }

  # Case 2: `- **Acceptance:**` block inside a Step (legacy PLAN.md §4)
  /^- \*\*Acceptance:?\*\*:?/ { mode = "sublist"; next }
  mode == "sublist" && /^(- \*\*|^#|^[[:space:]]*$)/ { mode = "" }
  mode == "sublist" && /^[[:space:]]+- (\[[ xX]\] )?/ {
    n++
    line = $0
    sub(/^[[:space:]]+- (\[[ xX]\] )?/, "", line)
    printf "AC-%02d  %s\n", n, line
    next
  }

  # Case 3: Inline `- **AC-1 ...:**` or `- **AC-1 ...**:` bullets (legacy PLAN.md §3)
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
    split($0, cols, "|")
    if (trim(cols[6]) != "") {
      n++
      printf "AC-%02d  %s — %s\n", n, trim(cols[3]), trim(cols[6])
    }
    next
  }
' "$file"
