# ShopFast checkout architecture (excerpt)

```
client -> gateway (nginx) -> order-svc -> payment-svc -> payment provider (PayNova)
```

* **gateway** – nginx. Access log format:
  `<ip> - <user_id> [<dd/Mon/yyyy:HH:MM:SS>] "<method> <path> HTTP/1.1" <status> rt=<seconds> upstream=<svc> trace=<trace_id>`
  * The timestamp is the time the response was sent (request completion).
  * ⚠️ The gateway hosts run in the Shanghai DC with system time zone **Asia/Shanghai (UTC+8)**, and the
    log format has **no offset**. All other services log in **UTC** (`...Z`).
  * `proxy_read_timeout` for `/api/v2/checkout` is **8 s**. If order-svc does not answer in time the gateway
    returns **502** (the backend may still finish the work).
* **order-svc** – JSON lines, UTC. Creates the order (`order.created`), calls payment-svc, then emits
  `order.payment_succeeded` or `order.payment_failed`.
* **payment-svc** – key=value text logs, UTC. One `charge.request` per attempt sent to PayNova and one
  `charge.result` per attempt (`result=succeeded|declined|timeout`, `duration_ms`; on timeout `duration_ms`
  is the client timeout). Calls to PayNova use a client timeout of **3000 ms**.
  * Every charge request carries an **idempotency key**. PayNova guarantees that requests with the *same*
    key create at most one charge; requests with *different* keys are always independent charges.
  * Split payments (gift card + card) intentionally use two different keys (`pi_<order>_gc`, `pi_<order>_card`)
    and produce two charges that together equal the order amount.
* **PayNova** – external provider. `provider_charges.csv` is their settlement export for the period
  (one row per charge they created, UTC). `status`: `succeeded`, `failed`, or `refunded` (a refunded
  charge had succeeded earlier and was later refunded in full).

`trace` / `trace_id` is propagated gateway -> order-svc -> payment-svc for checkout requests.
