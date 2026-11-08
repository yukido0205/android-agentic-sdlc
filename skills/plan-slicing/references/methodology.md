# Methodology — Why Contract-first + Parallel Mock Slices

## The problem it solves

Naive breakdown chains stories: Dev B (or Agent B) waits for Story A to finish,
then starts. Under time pressure B re-implements part of A's feature to unblock
itself → two divergent copies of the same model → merge conflicts, data drift,
and (with AI) each agent silently "fixing" the other's code.

Vertical Slicing + Technical Contract removes the wait AND the divergence:
- **Sources reconciled first** (by `/plan-feature`) so the Contract isn't built on a PRD, design or
  API doc that disagrees with the others.
- **Contract-first** gives every slice ONE agreed definition of shared types.
- **Mocks** let each slice run at 100% without the other's real code.
- **Integration** is a source swap, not a rewrite, because both sides matched
  the Contract.

## Step 0 — Reconcile the sources (done by `/plan-feature` Step 1)

PRD, Figma, API docs and the running code are each wrong sometimes. Read them
against each other; every disagreement becomes a numbered question with an owner
and an assumption in force, so no slice stalls waiting for the answer. Watch for:
- **"Existing X" claims** — often written from another platform. Grep first.
- **The spec contradicting itself** — read related sections together.
- **Design drawing what the spec forbids** (or vice versa) — a question, not a bug.

Report defects in someone else's docs; never repair them yourself.

## Step 1 — Extract the "common denominator"

Before assigning stories, run one tiny technical task (30–60 min): define only
what the stories genuinely SHARE.

- Include: fields/interfaces/state ALL affected stories need now.
- Exclude: fields only one story needs (those live inside that slice), and
  anything speculative (YAGNI — do not future-proof the Contract).
- Keep it minimal. A fat Contract couples slices back together and invites churn.

Output: `CONTRACT.md`, committed and versioned. This is the single source of
truth. Encode rules in types — a sealed state makes "two badges never show at
once" a compiler guarantee. A freeze nobody enforces is worse than an honest
draft: either require sign-off per amendment or label it draft.

## Step 2 — Turn "dependency" into "mock"

Instead of "B waits for A", B mocks A's Contract output:
- The mock is a fake that satisfies a Contract interface (e.g. a fake
  `CartRepository` returning a `CartState` with 2 sample items).
- B builds full UI + UX + logic against the mock and can be tested/demoed.
- A and B now proceed truly in parallel.

Every slice must be **vertical**: a thin end-to-end path (UI → logic → mocked
data) that delivers observable behavior — not a horizontal layer ("all the
ViewModels") that demos nothing on its own.

## Step 2b — Build consumers of data you don't have yet

When the backend lacks a field, don't wait: ship every consumer (enum, chip,
derived state) behind the type, and have the mapper return a fixed `UNKNOWN`.
When the field lands, one mapper function switches it all on. Two disciplines:
- The placeholder must **not lie** — `UNKNOWN` renders the neutral state, never
  an optimistic one the payload can't support.
- Every dead seam carries a KDoc saying what will make it live, so nobody deletes
  it as unused.

## Step 2c — Cut each slice into one-MR steps

A slice is too big for one review. Cut it into 3–5 steps, each one MR of
≤300 changed lines: no-UI logic → walking skeleton → happy path → errors →
polish. Each step must be safe to ship on its own. Full rules →
`execution-rules.md`.

## Step 3 — Integration

When A's real implementation lands, B changes only the wiring point (DI /
factory) from the mock to A's real object. No UI or logic edits, because the
shape never changed. Repeat per dependency until the Epic is whole.

## Worked example (mobile)

**Epic:** Checkout. **Story 1:** Cart screen. **Story 2:** Apply-discount popup.
Story 2 depends on Story 1 (need a cart to discount).

### Old way (dependency trap)
Wait for Story 1 → start Story 2. Under pressure, Story 2 re-creates a mini cart
to test the popup → two `CartState` definitions → conflict on merge, wrong totals.

### Contract-first way
1. **Contract:** agree `CartItem` + `CartState` (id, items, subtotal only) and
   `CartRepository` interface. Commit `CONTRACT.md` v1.0.0.
2. **Slice A (Cart):** build Cart UI + real total calc against `CartState`, real
   `CartRepository` impl.
3. **Slice B (Discount):** build discount popup + apply logic. For the cart it
   needs, inject a `FakeCartRepository` returning a `CartState` with 2 items.
4. **Acceptance:** QA tests Slice B on the mock → passes → Story 2 validated
   independently.
5. **Integration:** Slice A done → swap `FakeCartRepository` → real one at the
   `viewModelFactory` wiring. Epic complete.

Concrete Kotlin/Swift for each step → `mobile-contracts.md`.

## Anti-patterns (reject these)

- **Contract creep:** a slice adds a field to the Contract mid-flight without
  sign-off. Fix: park it in the slice; batch Contract amendments with team OK.
- **Mock mirrors internals:** the fake copies Story A's real logic instead of
  just satisfying the interface. Fix: mock returns static/fixture data only.
- **Horizontal slices:** "do all data layer", "do all UI" — nothing is demoable
  and everything blocks everything. Fix: slice per User Story, top to bottom.
- **Refactoring the Contract to be "cleaner":** forbidden once frozen; it desyncs
  every slice at once.
- **Optimistic placeholder:** a missing field defaults to `ACTIVE`/success. Fix:
  map unknown to the safe/neutral state.
- **Guessing past an ambiguity:** fix: add a `question-<NN>`, run on the assumption in force.
- **Mega-MR slice:** a whole slice in one MR. Fix: one step per MR, ≤300 lines.
- **Dashboard as truth:** ✅ ticked from memory. Fix: tick only on merge, with a
  commit verified against the tree.

## Checklist before handing off slices

- [ ] `/plan-feature` gates passed: every divergence and ambiguity is a `question-<NN>`;
      Phase 1 stories confirmed; P0 risks mitigated.
- [ ] Contract committed, versioned, freeze status stated honestly.
- [ ] Each slice is vertical (UI → logic → data) and independently demoable.
- [ ] Every cross-slice dependency has a named mock conforming to the Contract.
- [ ] Each slice names its exact integration swap point.
- [ ] Acceptance criteria per slice are satisfiable on the mock alone.
- [ ] Each slice is cut into 3–5 one-MR steps, no-UI logic first.
