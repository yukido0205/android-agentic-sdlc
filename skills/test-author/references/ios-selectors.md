# iOS Maestro Selectors & Conventions (UIKit & SwiftUI)

Load this reference when authoring Maestro test flows for iOS applications.

---

## 1. The Core Challenge of iOS UI Testing

Unlike Android where `android:id` or `Modifier.testTag` is ubiquitous, iOS apps (especially UIKit legacy) often lack explicit identifiers.
- **SwiftUI**: Requires `.accessibilityIdentifier("id_name")`.
- **UIKit**: Requires `view.accessibilityIdentifier = "id_name"` (which legacy codebases often omit).
- **Icon buttons** (Back chevron `<`, Close `X`, Cart 🛒) usually have NO text and NO default ID.

To prevent agent deadlock and avoid brittle pixel coordinates (`point: x, y`), follow the **iOS Selector Fallback Chain**.

---

## 2. iOS Selector Fallback Chain (Priority Order)

When targeting a node on iOS, evaluate selectors in this exact sequence:

### Priority 1: Semantic ID (`id:`)
Use if the element has an `accessibilityIdentifier`:
```yaml
- tapOn:
    id: "cart_btn_checkout"
```

### Priority 2: Text / Apple System Labels (`text:`)
Use for labeled buttons, titles, or standard iOS UIKit bar button items (Apple automatically assigns accessibility labels to system icons):
```yaml
# Static or button text
- tapOn:
    text: "Thanh toán"

# Apple standard UIKit system icons (UIBarButtonItem.SystemItem):
- tapOn:
    text: "Back"       # Or "Close", "Done", "Cancel", "Search"
```

### Priority 3: Relative Positioning (Essential for UIKit)
When an icon button or field has no ID and no unique text, anchor it relative to a stable text label:
```yaml
# Tap the interactive element directly below a known section header
- tapOn:
    below: "Tóm tắt đơn hàng"
    index: 0

# Tap an element to the right of a label
- tapOn:
    rightOf: "Mã giảm giá"
```

### Priority 4: Natural iOS Gestures (Navigation & Back)
On iOS navigation stacks (`UINavigationController`), never struggle to find a missing back button ID. Use the native iOS interactive pop gesture:
```yaml
# Standard iOS Edge Swipe Back (from left edge towards right)
- swipe:
    direction: RIGHT
    from:
      x: 5
      y: 300
```

### Priority 5: Controlled Testability Injection
If an icon button or custom control has no ID, no label, and cannot be reached via relative positioning:
- Under `rules/code-hygiene.md` §3.6, you are **explicitly allowed** to add `accessibilityIdentifier` to the view code:
  - **UIKit**: `btnDelete.accessibilityIdentifier = "cart_btn_delete"`
  - **SwiftUI**: `.accessibilityIdentifier("cart_btn_delete")`
- This is a safe 1-line metadata change with zero layout or logic impact.

### Priority 6: Relative Percentage Point (Absolute Last Resort)
If interacting with a custom Canvas, Map, or unlabelled graphic where no accessibility node exists, use **percentage coordinates** (`%`), NEVER raw pixel numbers:
```yaml
# Percentage coordinates scale reliably across iPhone SE, 15, and Pro Max
- tapOn:
    point: "50%, 80%"
```

---

## 3. Handling iOS System Alerts & Permissions

iOS presents system-level alerts for Permissions (Push Notifications, Location, Camera, Tracking).
Handle these gracefully in your flows:

```yaml
# Handle Notification / Location prompt if it appears
- runFlow:
    when:
      visible:
        text: ".*muốn gửi thông báo cho bạn.*|.*would like to send you notifications.*"
    commands:
      - tapOn: "Cho phép|Allow"
```

---

## 4. Closing the iOS Keyboard
iOS has no hardware back button to dismiss the keyboard. Use either:
```yaml
# Tap return / done on the keyboard
- pressKey: Enter

# Or tap anywhere outside the input field
- tapOn:
    above: "Tổng cộng"
```
