---
name: code-hygiene
description: Always-on coding guardrails enforcing Lean SOLID design (pre-code), Intent-Only documentation (during-code), and YAGNI simplification (post-code) across all Kotlin/Android, Swift/iOS, and Python code.
trigger: always_on
---

# Core Rule: Code Hygiene (Lean SOLID · Why-Only Docs · YAGNI Simplify)

Apply these three guardrails automatically whenever designing, writing, or modifying code — without waiting for a separate command.

---

## 1. Pre-Code: Lean SOLID Filter (Anti-Over-Engineering)
Run new classes, interfaces, or refactors through 5 reality checks before writing code:
1. **SRP (Single Responsibility):** *Can I describe what this class does without saying "and"?* ViewModel = UI state, Repository = coordinate data, UseCase = pure business rule.
2. **OCP (Open/Closed):** *Am I writing code for a requirement that hasn't been greenlit?* Design for extension only when needed; do not build speculative plugin/factory frameworks.
3. **LSP (Liskov Substitution):** *If I pass this subclass where the parent is expected, will it crash or throw `NotImplementedError` / `fatalError()`?* If yes, prefer composition or sealed types / Swift enums.
4. **ISP (Interface Segregation):** *Are implementers forced to write empty stubs or `TODO()`?* Keep interfaces focused; prefer Kotlin SAM/functional interfaces, Swift closures, or focused protocols.
5. **DIP (Dependency Inversion):** *Does this interface actually decouple two layers or have 2+ implementations (e.g., Real vs Fake/Mock)?* Never create 1:1 interfaces "because a book said so."

---

## 2. During-Code: High-Signal Documentation ("Why", Never "What")
Write self-documenting code first.
- **Strictly Prohibited:**
  - ❌ Syntax transliterations (`// Check if user is active` above `if (user.isActive)`).
  - ❌ Trivial KDoc/docstrings that repeat method/parameter names (`/** Gets the ID. @return the id */`).
  - ❌ Ghost changelogs (`// modified by ...`) or citations to local `plans/` / Figma node IDs.
- **Mandatory Comments:**
  - ✅ **Counter-intuitive "Why":** Business compliance rules, deliberate performance trade-offs.
  - ✅ **External Workarounds:** Third-party library bugs, Android OS/OEM quirks, iOS version/UIKit layout quirks, backward compatibility.
  - ✅ **Implicit Invariants:** Threading/coroutine/actor confinement, locking assumptions, non-obvious contracts.
- **Fact-Checked Claims:** Any comment stating a causal claim (*"X is created in Y"*, *"Z never runs here"*) MUST be verified by reading that exact line in the current session. Never write a plausible guess as fact.

---

## 3. Post-Code: De-Bloating & YAGNI Filter (Before Testing / Review)
Audit the diff of every modified file before running tests:
1. **Strip Speculative Generalization:** Remove unused parameters, default flags added "for future use", and single-implementation wrappers.
2. **No Test-Only Public API:** Never widen visibility to `public` solely for unit tests (in Kotlin use `internal` + `@VisibleForTesting`; in Swift use `@testable import`).
3. **Flatten Nesting:** Replace deep `if/else` pyramids with early returns / guard clauses (`guard let user = user, user.isActive else { return }` or `if (user == null || !user.isActive) return`).
4. **Remove Debug Cruft & Dead Code:** Delete temporary `Log.d` / `Timber.d` (Android), `print()` / `NSLog` (iOS), unused variables, and commented-out code blocks.
5. **30-Second Reviewer Check:** Every changed line in `git diff` must have an obvious, immediate reason to exist.
6. **Controlled Testability Injection:** Adding `accessibilityIdentifier` (UIKit / SwiftUI) or `testTag` (Compose) to interactive elements that lack IDs is an approved, safe 1-line change with 0 visual/runtime regression risk.
