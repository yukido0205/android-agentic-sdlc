# Kotlin Clean Architecture UseCase Patterns

This guide provides standard idiomatic patterns for writing UseCases / Interactors in Kotlin Android.

---

## 1. Single Action via `operator fun invoke`

Every UseCase must have **one single public responsibility** and expose it through the invoke operator.

```kotlin
class CalculateCartDiscountUseCase @Inject constructor(
    private val discountPolicyRepository: DiscountPolicyRepository
) {
    suspend operator fun invoke(cart: Cart, couponCode: String?): Result<DiscountedCart, DiscountError> {
        if (cart.items.isEmpty()) {
            return Result.failure(DiscountError.EmptyCart)
        }
        
        val policy = discountPolicyRepository.getPolicyForCoupon(couponCode)
        val discountAmount = policy.calculate(cart.subtotal)
        
        return Result.success(
            DiscountedCart(
                originalCart = cart,
                discountAmount = discountAmount,
                finalTotal = cart.subtotal - discountAmount
            )
        )
    }
}
```

---

## 2. Sync vs Async vs Reactive (Flow) UseCases

Choose the right execution model:

| Type | When to Use | Function Signature |
| :--- | :--- | :--- |
| **Pure Computation (Sync)** | In-memory calculations, input validations, pure algorithmic rules | `operator fun invoke(params): DomainModel` |
| **One-Shot Asynchronous (Suspend)** | Single network/database queries combined with business validation | `suspend operator fun invoke(params): DomainResult` |
| **Observable Stream (Flow)** | Live database queries, real-time status updates with domain transformations | `operator fun invoke(params): Flow<DomainState>` |

---

## 3. Modeling Domain Errors with Sealed Interfaces

Never throw generic `Exception` for business rule violations. Use sealed interfaces for exhaustive `when` handling in the Presentation layer:

```kotlin
sealed interface CheckoutValidationResult {
    data object Valid : CheckoutValidationResult
    
    sealed interface Failure : CheckoutValidationResult {
        data class OutOfStock(val unavailableItemIds: List<String>) : Failure
        data class MinimumOrderNotMet(val minAmount: BigDecimal, val currentAmount: BigDecimal) : Failure
        data object UserAccountSuspended : Failure
    }
}
```

---

## 4. Pure Value Objects with Invariant Enforcement

Encapsulate validation logic inside value objects so invalid states cannot exist in the domain:

```kotlin
@JvmInline
value class Quantity private constructor(val value: Int) {
    companion object {
        fun of(value: Int): Result<Quantity, DomainError.InvalidQuantity> {
            return if (value in 1..99) {
                Result.success(Quantity(value))
            } else {
                Result.failure(DomainError.InvalidQuantity(value))
            }
        }
    }
}
```
