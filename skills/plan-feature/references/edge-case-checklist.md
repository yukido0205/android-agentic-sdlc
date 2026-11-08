# Edge Case Discovery Checklist

Run these probes against every use case in Step 1. A brief almost never mentions
them; each hit becomes an Open Question, an acceptance criterion, or a risk row.
Hits under **Network & failure** and **Lifecycle & navigation** become
acceptance lines checked on a device — a risk row alone is not enough, because
nothing makes a risk row get tested.

## State & data

- Empty: zero items, first-run, brand-new account. What does the screen show?
- One item vs. hundreds vs. thousands — does the list paginate? Does it lag?
- Maximum lengths: long names, long addresses, multi-line text, emoji.
- Numeric extremes: 0, negative, very large IDs (a big numeric ID stored as a
  floating-point value loses precision or renders in scientific notation).
- Nullability: which fields can the server actually omit, vs. which the model
  declares non-null?
- Stale cache: cached payload written by an older app version, missing a field
  the new code requires.

## User & permissions

- Logged out / guest / expired token mid-flow.
- Free vs. paid tier; feature gated by entitlement or role.
- OS permission denied, denied-forever, or revoked while the app is backgrounded
  (location, camera, notifications, storage).
- Multiple accounts on one device — does the previous user's data leak in?

## Network & failure

- Offline at start; goes offline mid-flow; flaky/slow connection.
- Server 4xx vs. 5xx vs. timeout — is each distinguishable to the user?
- Duplicate submission: the user taps twice, or retries after a timeout that
  actually succeeded (idempotency).
- Partial success: 3 of 5 uploads land.
- Response schema drift / unknown enum value from the server.

## Lifecycle & navigation

- Process death and restore — is the in-progress state durable, or does a
  `lateinit`/implicitly-unwrapped field crash on re-creation?
- Rotation, split screen, font-size change, dark mode.
- Backgrounded during an async operation; deep link straight into the middle of
  the flow; back press mid-form (does unsaved work warn?).
- The same screen reachable from two entry points with different hosts.

## Abandonment & armed state

The highest-value probe in this list. Whenever a flow *configures* something that
will act later (a schedule, a subscription, a recurring job, a reminder):

- The user abandons the flow half-way — does the configured automation stay
  **armed**? Would it act on the user's behalf without them ever confirming?
- Which step actually arms it: the intermediate save, or the final confirmation?
- Publishing/creating and *sending/notifying* are separate acts — if the brief
  splits them ("post ≠ send"), state exactly what each one commits.
- Process death or a force-quit at every step of the chain — same question.

## Entity lifecycle & history

- Removing a participant/item that already has history (sends, replies, orders,
  messages): does the history survive, disappear, or become orphaned?
- Does removal stop future effects only, or retroactively erase past ones?
- Adding a participant mid-cycle: do they get the backlog, an intro, or nothing?
  Does the addition count as a round/event for analytics and for caps?
- Editing the parent after children exist — which children re-render from the new
  data and which are frozen at their creation values?

## Shared caps & fairness

- When several items compete for one rate limit or quota, who wins — and does the
  same one always win? A first-wins rule plus a daily cap means item B may never
  get through.
- Is the cap enforced client-side, server-side, or both? A client counter and a
  server suppression rule will disagree eventually.
- Does a suppressed/dropped action still increment a user-visible counter? If
  yes, the UI reports something that never happened.

## Silent failure of background work

- A scheduled job stops (credentials revoked, quota exhausted, entity expired) —
  how does the user find out? A background task that quietly stopped is worse
  than one that never started, because the user still believes it is running.
- Distinguish *stopped* (terminal, by design) from *paused* (recoverable) and
  give the recoverable case a visible prompt.

## Concurrency & ordering

- Two writes racing (local edit vs. incoming sync).
- Out-of-order responses — a stale request resolving after a fresh one.
- Rapid repeat taps; scroll during a data refresh.

## Time, locale, units

- Time zones, DST boundaries, "today" near midnight, clock skew.
- Number/date formats, RTL layout, translated strings that are 2× longer.
- Units: lbs vs. kg, miles vs. km, currency.

## Accessibility

- Screen-reader labels on every interactive element.
- Touch targets ≥ 48dp (Android) / 44pt (iOS).
- Contrast, dynamic type / font scaling, no meaning conveyed by color alone.

## Analytics & observability

- Which events fire, with what properties, and from which entry point?
- **Is the funnel closed?** Trace the feature's business claim end to end — if it
  says "turns X into Y", is there an event on Y attributable back to X? A funnel
  that stops one hop short cannot prove the feature worked.
- **Is every state-changing control instrumented?** Settings sheets, toggles and
  pickers are routinely omitted — and a retention/churn toggle is often the most
  important signal in the feature.
- Does a server-fired event need a value only the client knows (entry point,
  surface, source)? If so, the client must pass it at configuration time — make
  that an explicit contract item, not an assumption.
- **Is the metric you are extending already broken?** Check the existing event's
  current payload before adding a parameter beside it. A new field next to one
  that is always null, mis-sourced, or double-counted produces a funnel nobody
  can read — and the new field gets blamed. Fix the existing one first, in its
  own change.
- **Does the new name collide with an existing one on the same event?** Two
  unrelated concepts sharing a word (`frequency` for recurrence vs `cadence` for
  email) will be joined by whoever queries it later. Name them apart, and say so
  to whoever owns the dashboards.
- Can the failure path be diagnosed from logs without a repro?

## Rollout

- Behind a flag? What is the off-state behavior, and what is the kill switch?
- Does an old app version tolerate the new server response?
