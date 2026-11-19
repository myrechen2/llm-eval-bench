# Finance: reconciliation rules

* All amounts are in **minor units** (fen for CNY, cents for USD).
* For an order, the amount the customer **owes** is `amount_minor` if the order `status` is `paid`,
  and **0** otherwise (`payment_failed`, `cancelled`, ...).
* **Outstanding refund** of an order = (sum of its charges whose `status` is `succeeded`) − owed,
  floored at 0. Charges already `refunded` are settled and do not count.
* An **extra charge** is a charge (status `succeeded` or `refunded`) that pushes the running total of the
  order's successful charges — taken in `created_at_utc` order — above the owed amount.
* For cross-currency totals use the fixed rate **1 USD = 7.10 CNY**.
