# iOS Clean Architecture Layer Boundaries & Rules

This reference outlines the separation of concerns between layers in a modern Swift iOS project (supporting both UIKit legacy and SwiftUI).

---

## 1. The 3 Architectural Layers (Swift / iOS)

```
 ┌────────────────────────────────────────────────────────┐
 │ Presentation Layer (UI / Views)                        │
 │ - SwiftUI Views, UIViewController, UIView, Coords      │
 │ - ViewModels / Presenters (ObservableObject, State)    │
 └───────────────────────┬────────────────────────────────┘
                         │ depends on
 ┌───────────────────────▼────────────────────────────────┐
 │ Domain Layer (/Domain/ or CoreDomain package)          │
 │ - Pure Swift (NO UIKit, SwiftUI, CoreData, SwiftData)  │
 │ - Entities, Value Objects, Domain Enums                │
 │ - UseCases / Interactors (Single responsibility)       │
 │ - Repository Protocols (Domain contracts)              │
 │ - Domain Errors & Swift Result types                   │
 └───────────────────────▲────────────────────────────────┘
                         │ implemented by
 ┌───────────────────────┴────────────────────────────────┐
 │ Data Layer (Data / Infrastructure)                     │
 │ - Repository Implementations                           │
 │ - Data Sources: URLSession / Alamofire, CoreData, DB   │
 │ - DTOs (Decodable) & CoreData / SwiftData Models       │
 │ - Mappers: DTO/ManagedObject <-> Domain Model          │
 └────────────────────────────────────────────────────────┘
```

---

## 2. Layer Placement Checklist

| Responsibility | Belongs In | Forbidden In |
| :--- | :--- | :--- |
| Discount, Pricing, Fee Calculations | **Domain** (`UseCase` / `DomainModel`) | `UIViewController`, `ViewModel`, `APIManager` |
| Eligibility & Invariant Validations | **Domain** (`UseCase` / `ValueObject`) | `View`, `UIViewController`, `Model` |
| State Machine / Status Transitions | **Domain** (`DomainModel` / `UseCase`) | `UIViewController`, `View` |
| UI State (`@Published`, UI bindings) | **Presentation** (`ViewModel` / `ObservableObject`) | `Domain`, `Data` |
| Task/Async Concurrency Scope (`@MainActor`) | **Presentation** (for UI binding) | `Domain` (Use generic `async/await` without `@MainActor`) |
| Apple UI Frameworks (`UIKit`, `SwiftUI`, `UIImage`, `UIColor`) | **Presentation** | **Strictly Forbidden in Domain** |
| Persistence (`CoreData`, `SwiftData`, `UserDefaults`, `Keychain`) | **Data** (Data Sources) | `Domain`, `Presentation` |
| Network DTOs, API Requests (URLSession, Alamofire) | **Data** | `Domain` |

---

## 3. Detection Heuristics (Signs of Leaking Business Logic in Legacy iOS)

When scanning legacy iOS code (e.g. `CartViewController.swift` or `OrderManager.swift`), look for these code smells:

1. **Calculations or validation inside `IBAction` or delegate methods**:
   * *Smell:* In `CheckoutViewController`:
     ```swift
     @IBAction func didTapCheckout(_ sender: UIButton) {
         if cartTotal > 500 && user.points >= 50 {
             let discount = cartTotal * 0.1
             ...
         }
     }
     ```
   * *Fix:* Extract pure logic into `CalculateCartDiscountUseCase.swift` inside `/Domain/Checkout/`.

2. **CoreData `NSManagedObject` or Realm models used as Domain models**:
   * *Smell:* Passing `OrderMO` directly to UI and checking properties directly for business decisions.
   * *Fix:* Create a pure Swift struct `Order` in Domain and write a mapper `OrderMO.toDomain()`.

3. **Returning UI-facing strings directly from business logic**:
   * *Smell:* A helper returning `"Mã giảm giá đã hết hạn"` or `NSLocalizedString(...)`.
   * *Fix:* Return typed domain error enum (e.g. `CouponError.expired`), let Presentation layer map it to localized strings.

4. **Retain cycles & `[weak self]` in business algorithms**:
   * *Smell:* Long closures inside ViewControllers doing business math and using `self?.doSomething()`.
   * *Fix:* UseCases in Domain are stateless pure structs or classes with no reference to Views or ViewControllers.

---

## 4. Standard Swift UseCase Template

```swift
// Domain/Cart/UseCase/CalculateDiscountUseCase.swift
import Foundation // Pure Swift standard library, NO UIKit/SwiftUI/CoreData

public struct CalculateDiscountUseCase {
    public init() {}

    public func execute(cart: Cart, voucher: Voucher?) -> Result<Decimal, CartDomainError> {
        guard let voucher = voucher else {
            return .success(0)
        }
        guard cart.totalAmount >= voucher.minSpend else {
            return .failure(.minimumSpendNotMet(required: voucher.minSpend))
        }
        let discount = min(cart.totalAmount * voucher.percentage, voucher.maxCap)
        return .success(discount)
    }
}
```
