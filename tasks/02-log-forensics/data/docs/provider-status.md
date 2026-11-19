# PayNova status page (copied 2026-03-14 18:05 CST)

**[Resolved] Elevated latency on charge API — cn-east region**

* 16:31 CST – Latency back to normal. Monitoring.
* 15:20 CST – We are seeing elevated latency on `POST /v3/charges`. A subset of requests take longer than
  usual; requests are still being processed. Clients should use idempotency keys when retrying.
* 14:30 CST – Investigating reports of slow responses.
