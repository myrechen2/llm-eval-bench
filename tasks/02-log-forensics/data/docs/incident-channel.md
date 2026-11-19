# #inc-0314-checkout (Slack export, times are CST / UTC+8)

**14:44 kwu (SRE):** checkout 502s on the gateway are climbing
**14:46 pzhao:** gateway pushed the keepalive change at 14:33 — could that be it? the timing lines up
**14:47 kwu:** shortening keepalive shouldn't touch upstream... rolling it back costs nothing though, let me look
**14:58 kwu:** keepalive is not it, upstream errors are all read timeouts
**15:05 support-amy:** users report being **charged twice**
**15:07 pzhao:** isn't the double charge just split payments? gift card + card produces two charges anyway
**15:10 pzhao:** order-svc v3.9.0 started rolling out at 15:08, should I pause it?
**15:12 hzhang (on-call IC):** don't touch anything yet. PayNova status page shows slow responses since 14:30
**15:20 hzhang:** but PayNova slowness should only make orders fail, it shouldn't charge twice...
**15:41 wliu:** payment-svc v2.14.0 went out this afternoon, it changed the timeout handling, checking now
**15:58 hzhang:** decision: roll payment-svc back to v2.13.4
**16:03 hzhang:** rollback done, watching
**16:25 support-amy:** we'll manually refund the obvious double charges first; list in progress
**16:40 hzhang:** PayNova recovered. Finance needs the exact refund list + amounts tomorrow; someone write the postmortem
**23:36 wliu:** v2.14.2 deployed, timeout retries now reuse the idempotency key
