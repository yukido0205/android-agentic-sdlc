# Example: Refactoring a Tangled ViewModel to Clean Domain

This example demonstrates how to extract business logic from a coupled Android ViewModel into a pure Kotlin Clean Architecture domain layer.

---

## 1. BEFORE (Tangled Legacy ViewModel)

```kotlin
// ❌ BAD: Mixed UI state, network calls, and critical business pricing rules
class LegacyCheckoutViewModel(
    private val api: PaymentApiService,
    private val userDao: UserDao,
    private val context: Context // Leaking Android Context!
) : ViewModel() {

    val uiState = MutableStateFlow<CheckoutUiState>(CheckoutUiState.Loading)

    fun applyCouponAndCheckout(cartItems: List<CartItemDto>, couponCode: String?) {
        viewModelScope.launch {
            // Embedded Domain Rule 1: Minimum total check
            val rawTotal = cartItems.sumOf { it.price * it.quantity }
            if (rawTotal < 10.0) {
                uiState.value = CheckoutUiState.Error(context.getString(R.string.min_order_error))
                return@launch
            }

            // Embedded Domain Rule 2: VIP Discount & Coupon Calculation
            val user = userDao.getCurrentUser()
            var discount = 0.0
            if (user.isVip) {
                discount += rawTotal * 0.15 // 15% VIP discount
            }
            if (couponCode == "SUMMER2026") {
                discount += 5.0
            }

            val finalAmount = maxOf(0.0, rawTotal - discount)

            // Direct API call
            val response = api.charge(user.id, finalAmount)
            if (response.isSuccessful) {
                uiState.value = CheckoutUiState.Success
            } else {
                uiState.value = CheckoutUiState.Error("Payment failed")
            }
        }
    }
}
```

---

## 2. AFTER (Extracted Clean Architecture)

### Domain Model (`domain/model/CheckoutPricing.kt`)
```kotlin
// Pure Kotlin, zero Android dependencies
data class CartItem(val id: String, val unitPrice: Double, val quantity: Int) {
    val total: Double get() = unitPrice * quantity
}

data class PricingResult(
    val subtotal: Double,
    val discountAmount: Double,
    val finalTotal: Double
)

sealed interface CheckoutError {
    data class MinimumOrderNotMet(val minRequired: Double, val actual: Double) : CheckoutError
    data object EmptyCart : CheckoutError
}
```

### Domain UseCase (`domain/usecase/CalculateCheckoutPricingUseCase.kt`)
```kotlin
// Pure business logic - 100% testable on standard JVM
class CalculateCheckoutPricingUseCase {
    operator fun invoke(
        items: List<CartItem>,
        isVipUser: Boolean,
        couponCode: String?
    ): Result<PricingResult, CheckoutError> {
        if (items.isEmpty()) return Result.failure(CheckoutError.EmptyCart)

        val subtotal = items.sumOf { it.total }
        if (subtotal < MINIMUM_ORDER_THRESHOLD) {
            return Result.failure(CheckoutError.MinimumOrderNotMet(MINIMUM_ORDER_THRESHOLD, subtotal))
        }

        var discount = 0.0
        if (isVipUser) {
            discount += subtotal * VIP_DISCOUNT_PERCENTAGE
        }
        if (couponCode.equals("SUMMER2026", ignoreCase = true)) {
            discount += SUMMER_COUPON_FIXED_DISCOUNT
        }

        val finalTotal = maxOf(0.0, subtotal - discount)
        return Result.success(PricingResult(subtotal, discount, finalTotal))
    }

    companion object {
        const val MINIMUM_ORDER_THRESHOLD = 10.0
        const val VIP_DISCOUNT_PERCENTAGE = 0.15
        const val SUMMER_COUPON_FIXED_DISCOUNT = 5.0
    }
}
```

### Refactored Presentation (`presentation/CheckoutViewModel.kt`)
```kotlin
@HiltViewModel
class CheckoutViewModel @Inject constructor(
    private val calculatePricingUseCase: CalculateCheckoutPricingUseCase,
    private val checkoutRepository: CheckoutRepository
) : ViewModel() {

    private val _uiState = MutableStateFlow<CheckoutUiState>(CheckoutUiState.Idle)
    val uiState: StateFlow<CheckoutUiState> = _uiState.asStateFlow()

    fun onCheckoutClicked(items: List<CartItem>, coupon: String?) {
        viewModelScope.launch {
            _uiState.value = CheckoutUiState.Loading
            val isVip = checkoutRepository.isCurrentUserVip()

            when (val pricingResult = calculatePricingUseCase(items, isVip, coupon)) {
                is Result.Failure -> {
                    _uiState.value = CheckoutUiState.ValidationError(pricingResult.error)
                }
                is Result.Success -> {
                    val paymentResult = checkoutRepository.processPayment(pricingResult.data.finalTotal)
                    _uiState.value = paymentResult.fold(
                        onSuccess = { CheckoutUiState.Success },
                        onFailure = { CheckoutUiState.PaymentError(it.message) }
                    )
                }
            }
        }
    }
}
```

---

## 3. Fast JVM Unit Test (`domain/usecase/CalculateCheckoutPricingUseCaseTest.kt`)

```kotlin
class CalculateCheckoutPricingUseCaseTest {

    private val useCase = CalculateCheckoutPricingUseCase()

    @Test
    fun `when subtotal is less than 10 dollars, returns MinimumOrderNotMet error`() {
        val items = listOf(CartItem("1", unitPrice = 4.0, quantity = 2)) // $8 total
        
        val result = useCase(items, isVipUser = false, couponCode = null)

        assertTrue(result is Result.Failure)
        assertEquals(10.0, (result.error as CheckoutError.MinimumOrderNotMet).minRequired)
    }

    @Test
    fun `when user is VIP, applies 15 percent discount`() {
        val items = listOf(CartItem("1", unitPrice = 100.0, quantity = 1))

        val result = useCase(items, isVipUser = true, couponCode = null)

        assertTrue(result is Result.Success)
        assertEquals(15.0, result.data.discountAmount)
        assertEquals(85.0, result.data.finalTotal)
    }
}
```
