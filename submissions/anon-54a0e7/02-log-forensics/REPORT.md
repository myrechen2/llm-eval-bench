# ShopFast 2026-03-14 支付重复扣款与网关 502 事故复盘报告

## 1. 事故根因（机制分析）

本次事故由外部支付渠道 **PayNova 响应延迟升高** 与 **`payment-svc` v2.14.0（发布单 `DEP-7731`）的超时重试幂等键缺陷** 叠加触发：

1. **为什么会重复扣款**：
   - `payment-svc` 调用 PayNova 的客户端超时为 `3000 ms`。当 PayNova 接口延迟超过 3000 ms 时，`payment-svc` 触发客户端超时，但 PayNova 服务端仍在后台继续处理该笔扣款请求并最终落账（`status=succeeded`）。
   - `DEP-7731`（`payment-svc v2.14.0`）将原本的“超时后查询状态（`charge.status_check`）”改为了“超时后直接重试扣款（最多 3 次）”，但在实现重试逻辑时，**每次重试都生成了一个全新的 `idempotency_key`（`idem_key`）**，而非复用同一次支付意图的幂等键。
   - 由于 PayNova 对不同 `idempotency_key` 的请求视为完全独立的扣款，当前序超时请求在 PayNova 侧实际成功、而重试请求也成功时，同一笔订单就会产生 2 笔甚至 3 笔成功扣款。更有甚者，部分订单第 1/2 次尝试在客户端超时后于 PayNova 侧成功扣款，但最后一次重试返回 `card_declined`，导致 ShopFast 侧将订单标记为 `payment_failed`（应收 `owed = 0`），而用户实际上已被扣款 1～2 次。
2. **为什么网关 502 激增**：
   - 网关 `/api/v2/checkout` 的 `proxy_read_timeout` 为 `8 s`。在 `v2.13.4` 中单次超时（3 s）加一次轻量 `status_check` 总耗时远低于 8 s；而 `v2.14.0` 开启最多 3 次重试加退避（例如 `3000 ms + backoff + 3000 ms + backoff + 2000 ms > 8000 ms`），导致 `order-svc` 响应时间超过 8 s，nginx 网关主动断开并返回 `502`（后台仍在继续执行完第 3 次扣款）。
3. **为什么之前/之后的版本没有问题**：
   - **之前（`v2.13.4`）与回滚后（`DEP-7740`）**：`retry_on_timeout=false, max_attempts=1, status_check_on_timeout=true`，超时后仅使用原 `idem_key` 调用 `charge.status_check` 查询，不发起新扣款。
   - **修复版本（`v2.14.2`，`DEP-7752`）**：重试时复用同一个 payment intent 的 `idempotency_key`，由 PayNova 的幂等机制保证同一 key 最多产生一笔扣款。

## 2. 关键证据

1. **`payment-svc.log`（重试生成不同 `idem_key` 导致同一订单多次扣款）**：
   - 订单 `O0314-003221`（第一笔产生 extra charge 的订单）：
     - `2026-03-14T06:40:39.501Z INFO [payment-svc v2.14.0] event=charge.request order=O0314-003221 attempt=1 idem_key=pi_e63defb623db13bac408 amount=14950 currency=CNY trace=35916bc85e5cd9f0`
     - `2026-03-14T06:40:42.501Z WARN [payment-svc v2.14.0] event=charge.result order=O0314-003221 attempt=1 idem_key=pi_e63defb623db13bac408 result=timeout duration_ms=3000 trace=35916bc85e5cd9f0`
     - `2026-03-14T06:40:42.766Z INFO [payment-svc v2.14.0] event=charge.request order=O0314-003221 attempt=2 idem_key=pi_220fcea2cd9e0cdda14d amount=14950 currency=CNY trace=35916bc85e5cd9f0`
     - `2026-03-14T06:40:44.812Z INFO [payment-svc v2.14.0] event=charge.result order=O0314-003221 attempt=2 idem_key=pi_220fcea2cd9e0cdda14d result=succeeded charge_id=ch_f3c69d1fae2b8a3a duration_ms=2046 trace=35916bc85e5cd9f0`
   - 对应 `provider_charges.csv` 中，第一次超时的 `pi_e63defb623db13bac408` 实际上在 `2026-03-14T06:40:43Z` 成功生成了 `ch_9dd7d5c265b7ebfa`，第二次重试的 `pi_220fcea2cd9e0cdda14d` 又在 `2026-03-14T06:40:44Z` 成功生成了 `ch_f3c69d1fae2b8a3a`（首笔 extra charge）。
2. **`order_id=O0314-003351`（订单状态 `payment_failed`，却被成功扣款两次，同时触发网关 502）**：
   - 用户 `U100670` 的订单 `O0314-003351`（金额 `64500` USD cents）：`attempt=1`（`pi_0ae2a3da67b09c49cb76`）和 `attempt=2`（`pi_adc17b241b49c74ac005`）均在 3000 ms 客户端超时，但在 `provider_charges.csv` 中分别于 `06:53:07Z`（`ch_63aa0c4722dda1ad`）和 `06:53:10Z`（`ch_ae357fb38500077d`）扣款成功；`attempt=3`（`pi_c6a5a4cbfc1cf98c6475`）于 `06:53:13Z` 返回 `declined`。
   - `order-svc.jsonl` 在 `06:53:13.177Z` 记录 `event=order.payment_failed`，故该订单应收金额为 `0`，两笔 `64500` USD 全部成为未退余额（共 `129000` USD cents = `915900` CNY fen）。
   - `gateway-access.log` 记录 `10.36.199.186 - U100670 [14/Mar/2026:14:53:12] "POST /api/v2/checkout HTTP/1.1" 502 rt=8.000 upstream=order-svc trace=7f9430e64538abec`（总耗时触及 8.000s 网关读超时）。
3. **耗时与超时率统计证据**：
   - 在 `[04:40:00Z, 06:40:00Z)` 窗口内，`charge.result` 的 `duration_ms` p95 为 `2456 ms`；而在 `[06:40:00Z, 08:02:30Z)` 事故窗口内，1254 次尝试中有 400 次超时（超时率 `31.9%`），p95 达到客户端超时上限 `3000 ms`，并在网关侧产生 `88` 次 `POST /api/v2/checkout` 502 响应。

## 3. 事故时间线（统一使用 UTC）

- **2026-03-14 06:30:00Z**（14:30 CST）：PayNova `cn-east` 区域 `POST /v3/charges` 出现响应延迟升高。此时 `payment-svc` 仍为 `v2.13.4`，超时后走 `status_check`，未发生因重试导致的重复扣款。
- **2026-03-14 06:33:20Z**：网关发布 `DEP-7729`（调整 nginx `keepalive_timeout`）。
- **2026-03-14 06:36:10Z – 06:40:00Z**：**致因发布 `DEP-7731`**（`payment-svc v2.14.0`）上线，开启超时重试（最多 3 次）并移除 `status_check`。
- **2026-03-14 06:40:44Z**：订单 `O0314-003221` 产生本次发布后的第一笔 extra charge（`ch_f3c69d1fae2b8a3a`）。
- **2026-03-14 06:44:00Z**：SRE 发现网关 checkout 502 攀升。
- **2026-03-14 07:05:00Z**：客服收到用户反馈被重复扣款。
- **2026-03-14 07:58:40Z – 08:02:30Z**：**止血发布 `DEP-7740`** 完成，将 `payment-svc` 回滚至 `v2.13.4`。最后一笔受影响请求（在 `08:02:28.260Z` 回滚完成前由 `v2.14.0` 发出的 `O0314-004083` attempt 2）于 `08:02:30Z` 落账后，重复扣款彻底停止。
- **2026-03-14 08:25:00Z 起**：客服团队对部分明显重复扣款进行人工退款（共 97 笔 extra charge 被标记为 `refunded`，但仍有 141 笔订单存在未退余额）。
- **2026-03-14 08:31:00Z**（16:31 CST）：PayNova 延迟恢复正常。
- **2026-03-14 15:30:00Z – 15:34:00Z**：`DEP-7752`（`payment-svc v2.14.2`）上线，修复超时重试复用幂等键的问题。

## 4. 排除的误导线索与依据

1. **误导线索 1：网关 `DEP-7729` 修改 `keepalive_timeout 65s -> 30s` 导致 502**
   - **排除依据**：网关日志中所有 checkout 502 的响应时间均为 `rt=8.000`，对应 `docs/architecture.md` 中 `/api/v2/checkout` 的 `proxy_read_timeout = 8s`，说明是上游 `order-svc -> payment-svc` 多次重试耗时超过 8 秒触发读超时，与客户端/网关 keepalive 无关。
2. **误导线索 2：组合支付（Split payments，礼品卡 + 银行卡）被误认为重复扣款**
   - **排除依据**：组合支付使用 `pi_<order>_gc` 与 `pi_<order>_card` 两个幂等键，两笔扣款金额之和恰好等于订单 `amount_minor`（未超出应收金额 `owed`）。而事故期间的 extra charges 是对同一笔完整订单金额生成了多个随机 `pi_<hex>` 幂等键并多次全额扣款。
3. **误导线索 3：`order-svc v3.9.0`（`DEP-7735`，07:08Z–07:12:40Z 发布）或早上 `O0314-001701` 的多扣款**
   - **排除依据**：大面积 extra charges 从 `06:40:44Z` 即开始出现，早于 `DEP-7735` 近 28 分钟；而 `03:12:21Z` 的 `O0314-001701` 是早间两条不同 `trace_id` 并发请求产生的孤立个例（且已于 `03:33:21Z` 退款），与下午 `v2.14.0` 单次 trace 内部重试循环无关。
4. **误导线索 4：时区与已退款订单陷阱**
   - **排除依据**：`gateway-access.log` 使用无时区偏移的 `Asia/Shanghai (UTC+8)` 时间戳，必须减 8 小时对齐到 UTC 窗口 `[06:40:00Z, 08:02:30Z)`（即本地时间 `14:40:00` 至 `16:02:30`）；同时客服在事故后已人工退回部分款项（`status=refunded`），计算当前需退款订单（141 单）时必须剔除已退款记录，仅统计 `status=succeeded` 超出 `owed`（注意 `payment_failed` 订单 `owed=0`）的部分。

## 5. 修复与预防建议

1. **幂等键生命周期绑定**：幂等键必须在支付意图（Payment Intent）或订单支付单级别生成并持久化，所有针对同一支付意图的网络超时重试必须强制复用同一 `idempotency_key`，并在单元测试和集成测试中加入“超时重试幂等键一致性”断言。
2. **超时预算对齐（Timeout Budget）**：网关 `proxy_read_timeout`（8 s）必须大于下游最大可能耗时（或将 `payment-svc` 最大重试次数/超时时间调小，例如最多 2 次尝试或采用异步回调确认），避免网关返回 502 而后台继续扣款造成状态不一致。
3. **自动对账与兜底冲正**：建立准实时对账任务，对比 `provider_charges` 成功流水与内部订单状态（尤其是内部状态为 `payment_failed` 但渠道侧 `succeeded` 的悬空扣款，以及同一订单多笔 `succeeded` 流水），发现差错自动告警并触发退款。
4. **日志时区标准化**：将上海机房 nginx 网关访问日志的时间格式统一改为带时区偏移的 ISO-8601（`$time_iso8601`）或统一使用 UTC，消除跨源日志关联的时区歧义。
