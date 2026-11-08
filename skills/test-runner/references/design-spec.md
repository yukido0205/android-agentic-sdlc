# Design spec — design mode

Load this only when writing a spec. The spec is the Figma frame reduced to the numbers a reviewer
would check, so the comparison never needs an image.

## Format — `.maestro/<RUN>/design/<screen>.tsv`, tab-separated

```
# Figma <fileKey> node <id> — PRD §<n>        ← header: where every value came from
# id              prop              expected    note
post_btn          h                 48
post_btn          w                 328
post_btn          inset_left:root   16
title             gap_below:post_btn 24
post_btn          fill              #1A73E8
post_btn          fill@0.05,0.5     #1A73E8     sample the left edge, clear of the label
title             text              Schedule
```

| prop | meaning (dp) |
|---|---|
| `w`, `h` | node size |
| `gap_below:<id>` | this node's bottom → `<id>`'s top |
| `gap_right:<id>` | this node's right → `<id>`'s left |
| `inset_left:<id>`, `inset_top:<id>` | `<id>`'s left/top → this node's left/top (a parent or container) |
| `fill[@fx,fy]` | hex colour at that fraction of the node (default centre — move it off any text/icon) |
| `text` | an exact string on the node or one of its children |

## Getting the values cheaply

1. **`.claude/figma-cache/` first.** Only on a miss call `get_design_context` for the **one frame
   node**, never the page. Save what you extract back to the cache.
2. **Read `PLAN.md §1` (Sources & Frames)** of the epic before trusting a node: it lists stale frames and known traps.
3. **Skip `visible: false` layers.** Design context leaks them (a fake icon or reply button has
   shipped this way). If it is hidden in Figma it is not a spec line.
4. **Measure, never guess.** No value in the spec without a Figma source. A gap Figma does not state
   (auto-layout absent) is left out, not estimated.
5. **Text comes from the PRD/strings, not Figma placeholder copy.** Figma shows "John Smith"; the
   screen shows fixture data. Assert labels and static copy only.

## Ids for nodes that have none

A spec line needs an id on the device. A node with none (decorative Compose `Box`, unnamed XML view)
cannot be measured: list it under `# unmeasurable:` in the header and say what to add (a test tag /
`android:id`). Adding the id is a code change — propose it, do not make it unasked.
