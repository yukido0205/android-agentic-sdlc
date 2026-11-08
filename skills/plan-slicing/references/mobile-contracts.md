# Mobile Contract, Mock & Integration Patterns

Concrete types for Step 1 (Contract), Step 2 (mocks), Step 3 (swap). Match the
repo's existing architecture; do not introduce a new pattern for one Epic.

## Android (Kotlin) — Contract types

```kotlin
// CONTRACT — shared data model (only fields all stories agree on)
data class CartItem(val id: String, val name: String, val price: Long)
data class CartState(val items: List<CartItem>, val subtotal: Long)

// CONTRACT — repository interface (signatures only, no impl)
interface CartRepository {
    fun observeCart(): Flow<CartState>
    suspend fun refresh()
}

// CONTRACT — MVI, handleIntent style: one data-class state, intents in, events out
enum class LoadState { Idle, Loading, Failed }
data class CartUiState(val cart: CartState? = null, val load: LoadState = LoadState.Idle)

sealed class CartIntent {
    data object Refresh : CartIntent()
}

sealed class CartEvent {
    data class ShowError(val message: String) : CartEvent()
}
// ViewModel: fun handleIntent(intent: CartIntent); uiState: StateFlow; events: SharedFlow
```

Rules: expose immutable `List`/`StateFlow`; one `data class` UiState with sealed/enum
fields for finite states (not a sealed Loading/Ready/Error UiState); one-time output
is an `Event` via `MutableSharedFlow`, not `Effect`/`Channel`; keep
the model flat and serialization-safe (Gson/prefs pitfalls — flat enums/
primitives, not abstract-typed fields).

## Android — mock (fake impl of the Contract)

```kotlin
// Slice B uses this to build/test without Slice A's real code.
class FakeCartRepository : CartRepository {
    private val sample = CartState(
        items = listOf(
            CartItem("1", "Item A", 1000),
            CartItem("2", "Item B", 2500),
        ),
        subtotal = 3500,
    )
    override fun observeCart(): Flow<CartState> = flowOf(sample)
    override suspend fun refresh() = Unit
}
```

The mock returns fixtures ONLY. It must not re-implement Slice A's real logic.

## Android — mock → real swap (manual DI)

This repo wires deps in `viewModelFactory` (no DI framework). The swap is one
line at the wiring point:

```kotlin
// Slice B during parallel build — mock:
private val viewModel: DiscountViewModel by viewModelFactory {
    DiscountViewModel(cartRepository = FakeCartRepository())
}

// Integration — real (Slice A landed). Only this line changes:
private val viewModel: DiscountViewModel by viewModelFactory {
    DiscountViewModel(cartRepository = CartRepositoryImpl.getInstance())
}
```

Compose preview / test mock:
```kotlin
@Preview @Composable
fun DiscountPreview() = DiscountScreen(state = CartUiState(cart = fakeCart))
```

## Android — placeholder for data the backend doesn't send yet

```kotlin
// CONTRACT — UNKNOWN is the safe state; consumers render it as neutral.
enum class OrderState { ACTIVE, PAUSED, EXPIRED, UNKNOWN }

/**
 * Payload has no `state` field yet, so every order is UNKNOWN.
 * Goes live when the API returns `state`: map it here; no consumer changes.
 */
fun OrderDto.toState(): OrderState = OrderState.UNKNOWN

// After the field lands — unrecognised values still fall to the safe state:
fun OrderDto.toState(): OrderState =
    OrderState.entries.firstOrNull { it.name == state?.uppercase() } ?: OrderState.UNKNOWN
```

Never default to `ACTIVE`/success: a happy-path step that merges alone must not
claim what the payload can't prove. This mapper is worth a test; plain
field-copy mappers are not.

## iOS (Swift) — Contract types

```swift
// CONTRACT — shared model + protocol
struct CartItem: Equatable { let id: String; let name: String; let price: Int }
struct CartState: Equatable { let items: [CartItem]; let subtotal: Int }

protocol CartProviding {                       // -ing suffix per style guide
    func observeCart() -> AsyncStream<CartState>
    func refresh() async
}

enum CartUiState: Equatable {                  // enum for finite state
    case loading
    case ready(CartState)
    case failure(String)
}
```

## iOS — mock + swap (init injection)

```swift
struct FakeCartProvider: CartProviding {
    private let sample = CartState(
        items: [.init(id: "1", name: "Item A", price: 1000),
                .init(id: "2", name: "Item B", price: 2500)],
        subtotal: 3500)
    func observeCart() -> AsyncStream<CartState> { .init { $0.yield(sample); $0.finish() } }
    func refresh() async {}
}

// Parallel build:  DiscountViewModel(cart: FakeCartProvider())
// Integration:     DiscountViewModel(cart: CartService.shared)   // one line
```

SwiftUI preview mock: `DiscountView(state: .ready(fakeCart))`.

## Contract hygiene (both platforms)

- Version every change with a named approver; enforce the freeze or call it draft.
- Number sections (`§1.1`) and cite them by number in slices and steps.
- Unknown/unrecognised values map to the safe state, never the optimistic one.
- Only shared fields belong here — story-private fields stay inside the slice.
- No `!!` / force-unwrap; nullable/optional only where truly optional.
- Prefer the repo's existing Repository/UseCase style over a new abstraction.
