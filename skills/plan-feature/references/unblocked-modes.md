# Unblocked Development Playbook (Missing Figma / Missing Backend)

When developing mobile features, Figma designs and Backend APIs are often incomplete or delayed.
**Mobile must NEVER halt or get blocked.** Use this playbook to adapt the workflow based on available inputs.

---

## Input Maturity Tiers

| Tier | Available Inputs | Strategy | Primary Focus |
|---|---|---|---|
| **Tier 1** | PRD / Brief only (No Figma, No BE) | **Domain-First & Wireframe State** | Domain Logic, Use Cases, MVI ViewState, Local Mock Repository, Functional Skeleton. |
| **Tier 2** | PRD + Figma (No BE) | **Client-Driven API Proposal** | Derive payload from UI, propose DTO schema to BE, mock locally to unblock. |
| **Tier 3** | PRD + Figma + BE Docs | **Full Triad Reconciliation** | Standard 3-way reconciliation, Discrepancy Index, Anomaly Triangle. |

---

## Tier 1 Playbook: PRD Only (No Figma, No Backend)

When neither Design nor Backend is ready:

### 1. Executive Summary
Start the analysis with:
```markdown
[Tier]: Tier 1 (Domain-First — PRD baseline, Design & BE pending)
[Red Flags]: None (PRD baseline accepted).
[Missing Data]: BE API & Figma design pending.
[Strategy]: Mobile drafts Local Mock Contract + ViewState Skeleton. Progress is 100% unblocked.
```

### 2. Domain & Logic First (Clean Architecture)
- Extract pure **Domain Entities** from the PRD business rules (independent of API JSON).
- Implement business logic in isolated **UseCases** (`Get...UseCase`, `Validate...UseCase`).
- Define UI state as an immutable **MVI ViewState**:
  - `Loading`
  - `Content(data: DomainModel)`
  - `Empty(reason: String)`
  - `Error(error: DomainError)`

### 3. Functional Wireframe Skeleton (No Pixel Pushing)
- Build a functional skeleton UI (basic layout using existing design tokens/components).
- Wire all interactive user actions to the ViewModel and UseCases.
- **Do not guess visual styling.** Visual skinning, padding polish, and Figma fidelity are deferred to Phase 2 once designs land.

### 4. Local Mock Repository
- Implement a `MockRepository` providing synthetic data, network delay (`delay(500)`), and simulated error toggles.
- Never wait for a live backend.

### 5. Artifact Handling
- In `PLAN.md §1 (Sources)`:
  - `Figma`: `[Pending — Wireframe Skeleton]`
  - `API docs`: `[Pending — Local Mock]`
  - Skip the 3-way Discrepancy Index (focus only on PRD ambiguities).
- In `PLAN.md §2 (Questions & Assumptions)`:
  - **NEVER** ask "Where is Figma?" or "Where is the API?".
  - Record one unblocking assumption:
    > *"Assumption in force: Mobile proceeds with Domain-First architecture, functional ViewState skeleton, and local mock repository. UI skinning and remote API integration deferred to Phase 2."*

---

## Tier 2 Playbook: PRD + Figma (No Backend)

When Figma designs exist but Backend has no API:

### 1. Derive Data Payload from UI (Contract-First)
- Inspect Figma UI elements to identify all necessary data fields:
  - Form inputs → Request DTO.
  - Displayed lists, statuses, cards → Response DTO.
  - Pagination, search, filter keys → Query parameters.
- Define clean DTO structures under `data/dto/`.

### 2. Client-Driven API Proposal
- Propose the minimal JSON schema that satisfies UI requirements.
- Send a copy-pasteable Slack snippet to Backend (see template below).
- Adopt this schema immediately in a `MockRemoteDataSource`.

### 3. Artifact Handling
- In `PLAN.md §1 (Sources)`:
  - `API docs`: `[Pending — Proposed by Mobile]`
- In `PLAN.md §2 (Questions & Assumptions)`:
  - Record the proposed contract as an unblocking assumption with a deadline liability shift:

> 💬 **Copy & Paste to Slack/Teams (Proposed API Contract for BE):**
> 
> `@BE: For [<Feature Name>], Mobile has drafted a proposed API schema based on UI requirements:
> - **Endpoint:** `<POST/GET /api/vX/path>`
> - **Proposed Payload:**
> ```json
> {
>   "id": "string",
>   "status": "ACTIVE | PENDING | EXPIRED",
>   "items": [{ "name": "string", "quantity": 1 }]
> }
> ```
> *(Client is currently unblocked and developing against a local mock matching this schema. Please review by [Deadline: e.g. 5:00 PM tomorrow] if any fields need adjustment).*`

---

## Iron Rules for Incomplete Sources

1. **Never block development:** Missing specs must trigger an immediate mock/skeleton assumption.
2. **Never ask rhetorical questions:** Do not ask PM/Design "When will Figma be ready?" or BE "When will the API be deployed?". Ask only concrete architectural decisions or propose schemas.
3. **Clean Architecture guarantees safety:** When live API and final Figma arrive, only the `RemoteDataSource` and layout XML/Compose need updating — 0 lines of Domain business logic are touched.
