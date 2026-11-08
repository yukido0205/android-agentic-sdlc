# Issue Template

## Title
Example: [Android] Minimum order threshold ($10.00) is hardcoded in the client instead of using the server config value

### Summary
Write a short and clear summary. Example: On Android, the minimum order threshold ($10.00) is a compile-time constant and ignores the remote config payload, so changing the threshold requires an app update. The PRD requires reading `min_order_amount` from the configuration endpoint.

### Steps to reproduce

**Example**
1. Log in (test account `user@example.com`)
2. Open the Catalog tab
3. Add a $12.00 item to the cart
4. Open the Checkout screen
5. Observe the order summary row

### Expected result

**Example:** Per PRD §3.2, the order summary displays formatted labels for each value:
`Subtotal: $12.00  •  Discount: $0.00`

### Actual result

**Example:** The summary row renders raw unformatted values without labels:
`12.0 / 0.0 / STD`

