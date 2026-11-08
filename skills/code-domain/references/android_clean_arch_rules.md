# Android Clean Architecture Layer Boundaries & Rules

This reference outlines the separation of concerns between layers in a modern Kotlin Android project.

---

## 1. The 3 Architectural Layers

```
 ┌────────────────────────────────────────────────────────┐
 │ Presentation Layer (:feature:xxx or :ui)               │
 │ - Jetpack Compose, Views, Activities, Fragments        │
 │ - ViewModels (UI State, UI Events, Flow transformations)│
 └───────────────────────┬────────────────────────────────┘
                         │ depends on
 ┌───────────────────────▼────────────────────────────────┐
 │ Domain Layer (:core:domain or :domain)                 │
 │ - Pure Kotlin (NO android.* dependencies)              │
 │ - Entities, Value Objects, Domain Enums                │
 │ - UseCases / Interactors (Single responsibility)       │
 │ - Repository Interfaces (Domain contracts)             │
 │ - Domain Errors & Sealed Results                       │
 └───────────────────────▲────────────────────────────────┘
                         │ implemented by
 ┌───────────────────────┴────────────────────────────────┐
 │ Data Layer (:core:data or :data)                       │
 │ - Repository Implementations                           │
 │ - Data Sources: Retrofit APIs, Room DAOs, DataStore    │
 │ - DTOs & Room Entities                                 │
 │ - Mappers: DTO/Entity <-> Domain Model                 │
 └────────────────────────────────────────────────────────┘
```

---

## 2. Layer Placement Checklist

| Responsibility | Belongs In | Forbidden In |
| :--- | :--- | :--- |
| Discount, Tax, Cart Calculations | **Domain** (`UseCase` / `DomainModel`) | `ViewModel`, `Repository`, `Activity` |
| Eligibility & Invariant Validations | **Domain** (`UseCase` / `ValueObject`) | `ViewModel`, `Composable`, `DAO` |
| State Machine / Status Transitions | **Domain** (`DomainModel` / `UseCase`) | `ViewModel`, `Fragment` |
| UI State (`ScreenState`, `UiEvent`) | **Presentation** (`ViewModel`) | `Domain`, `Data` |
| Coroutine Scopes (`viewModelScope`) | **Presentation** (`ViewModel`) | `Domain` (pass suspending functions instead) |
| Android Framework (`Context`, `Toast`, `Intent`) | **Presentation** / **App** | **Strictly Forbidden in Domain** |
| Room DB, SQLite, SharedPrefs, DataStore | **Data** (Data Sources) | `Domain`, `Presentation` |
| Network DTOs, JSON parsing (Moshi, Kotlinx) | **Data** | `Domain` |

---

## 3. Detection Heuristics (Signs of Leaking Business Logic)

When scanning legacy code, look for these code smells:
1. **`if/when` blocks inside ViewModels performing rule checks**:
   * *Smell:* `if (user.points > 100 && cart.total > 50) applyDiscount()` in `ViewModel`.
   * *Fix:* Extract to `CalculateCartDiscountUseCase`.
2. **Data validation directly before network calls**:
   * *Smell:* `if (phone.length == 10 && phone.startsWith("09")) api.sendOtp(phone)` in Repository or ViewModel.
   * *Fix:* Extract `PhoneNumber` Value Object or `ValidatePhoneNumberUseCase`.
3. **Database entities used as UI models or domain models**:
   * *Smell:* `@Entity data class UserEntity` passed directly to Compose or used for business rule evaluation.
   * *Fix:* Introduce pure domain `data class User` and a `UserEntity.toDomain()` mapper.
4. **Android `Context` or `@StringRes` in business decisions**:
   * *Smell:* Domain logic returning string resource IDs (`R.string.error_invalid_coupon`).
   * *Fix:* Return typed domain sealed errors (e.g. `CouponError.Expired`), mapped to UI text in the presentation layer.
