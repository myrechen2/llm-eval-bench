# ShopFast 2026-03-14 支付重复扣款事故复盘报告（INC-0314）

## 1. 事故概述与影响
2026-03-14 06:40:00Z–08:02:30Z（14:40–16:02:30 CST）期间，`payment-svc` 上线 `v2.14.0`（`DEP-7731`）与 PayNova 渠道高延迟叠加，导致订单重复扣款及网关 `POST /api/v2/checkout` 出现 **88** 次 `502` 超时响应。全量对账显示，共 **188** 笔订单在事故期间产生 **237** 笔额外扣款；扣除客服已手动退款的订单后，仍有 **141** 笔订单存在未退金额（CNY **62,644.30 元** / `6264430` 分，USD **2,479.78 美元** / `247978` 分）。

## 2. 根因与触发机制
### 机制说明
`payment-svc` 调用 PayNova 的客户端超时时间为 `3000 ms`。当 PayNova 发生慢请求（耗时 >3000 ms）时，客户端会触发超时，但 PayNova 服务端往往仍会继续处理并完成该笔扣款（见 `docs/provider-status.md`）。

事故触发需要同时满足两个条件：
1. **外部诱因（PayNova 延迟升高）**：06:30Z 起 PayNova 响应延迟飙升，[06:40:00Z, 08:02:30Z) 内 `charge.result` 超时率达 **31.9%**（400/1254），P95 达到 **3000 ms**（前 2 小时窗口 P95 为 **2456 ms**）。
2. **代码缺陷（`DEP-7731` / `payment-svc v2.14.0`）**：该版本移除了超时后的幂等状态查询（`status_check_on_timeout=false`），改为最多 3 次自动重试（`retry_on_timeout=true, max_attempts=3`）。然而，**全部 368 次重试均重新生成了不同的 `idem_key`**（复用原 `idem_key` 的次数为 `0`）。由于 PayNova 仅对相同 `idem_key` 去重，不同 `idem_key` 的重试被视为独立扣款请求，导致：
   * 若前序超时请求已在 PayNova 成功而后续重试再次成功，用户被扣款 2–3 次；
   * 若多次重试均超时（如 `O0314-003351`、`O0314-004068`），`order-svc` 最终判定 `order.payment_failed`（客户应付金额为 `0`），但 PayNova 实际已成功扣款 1–3 次；
   * 多达 3 次 3000 ms 请求加退避时间（约 9–10 s）超过 nginx `proxy_read_timeout`（8 s），直接引发网关 `rt=8.000` 的 `502` 报错，用户侧以为失败但后台仍完成扣款。

### 为什么前后版本没有问题
* **回滚前/后版本 `v2.13.4`**：配置 `retry_on_timeout=false, max_attempts=1, status_check_on_timeout=true`。超时后通过原 `idem_key` 调用 `charge.status_check`（共 125 次，其中 69 次 `found=true`、56 次 `found=false`），既确认了真实扣款结果，又未超过网关 8 s 超时阈值，因此 06:30Z–06:40Z 与 08:02:30Z–08:31Z 虽同样存在 PayNova 慢请求（08:10Z 桶超时率仍达 33.6%），却未引发重试重复扣款和 8 s 502。
* **后续修复版本 `v2.14.2`（`DEP-7752`）**：修复为超时重试复用同一 `idem_key`，即使再遇超时也不会在 PayNova 创建新扣款。

## 3. 关键证据
1. **配置变更对比（`payment-svc.log`）**：
   * `2026-03-14T06:39:55.000Z INFO  [payment-svc v2.14.0] event=config.loaded provider_timeout_ms=3000 retry_on_timeout=true max_attempts=3 status_check_on_timeout=false`
   * `2026-03-14T08:02:25.000Z INFO  [payment-svc v2.13.4] event=config.loaded provider_timeout_ms=3000 retry_on_timeout=false max_attempts=1 status_check_on_timeout=true`
2. **第一笔事故额外扣款 `O0314-003221`（`payment-svc.log` + `provider_charges.csv`）**：
   * `2026-03-14T06:40:39.501Z` attempt=1 使用 `idem_key=pi_e63defb623db13bac408`，3000 ms 超时后触发 `charge.retry`，attempt=2 改用新 `idem_key=pi_220fcea2cd9e0cdda14d`；两笔请求均在 PayNova 扣款成功（`ch_9dd7d5c265b7ebfa` @ `06:40:43Z`、`ch_f3c69d1fae2b8a3a` @ `06:40:44Z`，各 14950 分 CNY）。
3. **最大未退用户 `U100670` 的失败订单重复扣款（`O0314-003351`）**：
   * `order-svc.jsonl` 显示该订单于 `06:53:13.177Z` 记为 `order.payment_failed`（`reason=declined`），网关返回 `502 rt=8.000`（`trace=7f9430e64538abec`），但 `payment-svc.log` 显示 attempt 1/2 超时后均更换了 `idem_key`（`pi_0ae2a3da67b09c49cb76`、`pi_adc17b241b49c74ac005`），最终 `provider_charges.csv` 产生两笔 `succeeded` 扣款（各 `64500` 美分），合计 `129000` 美分（折合人民币 `915900` 分）。
4. **`v2.13.4` 对照证据 `O0314-003200`**：
   * `06:38:42.167Z` 在 `v2.13.4` 超时后执行 `charge.status_check idem_key=pi_ab315a81a38a4442ac82 found=true charge_id=ch_8eea47cf4c7c2eb4`，仅产生 1 笔扣款，网关正常返回 `200 rt=3.434`。

## 4. 事故时间线（UTC）
* **06:30:00Z**（14:30 CST）：PayNova 出现延迟升高（`payment-svc` 开始出现 3000 ms 超时，由 `v2.13.4` 的 `status_check` 安全兜底）。
* **06:33:20Z**：`DEP-7729`（gateway `cfg-0314a`）发布完成，调整 `keepalive_timeout`。
* **06:40:00Z**：`DEP-7731`（`payment-svc v2.14.0`）发布完成（`config.loaded` 于 `06:39:55Z` 生效），开始以新 `idem_key` 重试超时请求，网关开始出现 `rt=8.000` 的结账 `502`。
* **06:40:44Z**：事故期第一笔额外扣款生成（`O0314-003221` / `ch_f3c69d1fae2b8a3a`）。
* **07:12:40Z**：`DEP-7735`（`order-svc v3.9.0`）发布完成。
* **08:02:30Z**：`DEP-7740` 回滚至 `payment-svc v2.13.4` 完成（最后 1 笔由 `v2.14.0` 在 `08:02:28.260Z` 发起的在途重试 `O0314-004083` 于 `08:02:30.521Z` 完成并随后被退款），重复扣款与结账 8 s `502` 立即停止。
* **08:31:00Z**（16:31 CST）：PayNova 延迟恢复正常。
* **15:34:00Z**：`DEP-7752`（`payment-svc v2.14.2`）发布完成，恢复超时重试并正确复用 `idem_key`。

## 5. 排除的误导线索与依据
1. **`DEP-7729`（gateway `keepalive_timeout` 变更）**：发布于 `06:33:20Z`，但其后至 `06:40:00Z` 网关结账 `502` 为 `0`；窗口内全部 88 次结账 `502` 的 `rt` 均为 `8.000`（精确命中 `proxy_read_timeout`），并非 keepalive 导致的连接复位。
2. **`DEP-7735`（`order-svc v3.9.0` 缓存预热）**：发布于 `07:12:40Z`，晚于首次重复扣款（`06:40:44Z`）逾 30 分钟；且 400 条 `cache.warmup_miss` 最大仅增加 `90 ms` 延迟，与重复扣款及 8 s 超时无关。
3. **拆分支付（`split`）猜想**：全量 353 笔 `split` 订单均使用固定规则 `pi_<order>_gc` 与 `pi_<order>_card`，核对无一笔出现总扣款与订单金额不符（异常数 `0`）。
4. **网关日志时区与早间 `502` 干扰**：`gateway-access.log` 采用无偏移的 `Asia/Shanghai (UTC+8)` 时间。若误将 `[14/Mar/2026:06:40..08:02]` 当作 UTC，会误统计前一晚 `22:40Z–00:02Z` 其他服务故障期遗留的快响应 `502`（`rt=0.214–1.400s`），而非本次事故的 `14:40–16:02 CST` 8 s 超时 `502`。
5. **事故前孤立重复扣款 `O0314-001701`**：发生于 `03:12:21Z`（`v2.13.4` 期间），由两条不同 `trace_id` 的并发结账请求导致，且已于 `03:33:21Z` 全额退款，与 `DEP-7731` 无关。

## 6. 修复与预防建议
1. **幂等键绑定业务意图**：将 `idem_key` 与订单/支付意图及支付方式强绑定并在跨重试、跨客户端并发请求间持久化复用（`v2.14.2` 已修复重试路径；同时建议对同订单并发结账增加状态锁，防止如 `O0314-001701` 的并发双扣）。
2. **保留超时状态核查（`status_check`）**：在重试之前或最终失败标记前查询渠道支付状态，避免将渠道已成功的订单错误标为 `payment_failed`。
3. **对齐全链路超时预算**：`max_attempts=3` × `3000 ms` + 退避时间超过网关 `8 s` `proxy_read_timeout`，应控制总重试预算在网关超时内或采用异步支付状态确认。
4. **统一日志时区与自动对账告警**：将网关日志时间戳改为带偏移的 ISO-8601 UTC 格式；建立准实时渠道结算对账监控，对超额扣款及失败订单扣款自动告警与阻断。
