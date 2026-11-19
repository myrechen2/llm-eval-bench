# 2026-03-14 ShopFast 支付重复扣款与网关 502 事故复盘报告

## 1. 根因分析

本次事故由 **外部支付渠道 PayNova 延迟升高** 与 **payment-svc `v2.14.0`（`DEP-7731`）的错误重试逻辑** 共同触发：

1. **重复扣款机制**：`payment-svc` 调用 PayNova 的客户端超时为 `3000 ms`。当 PayNova 从 `06:30 UTC`（`14:30 CST`）起出现高延迟时，部分请求超过 `3000 ms` 触发客户端 `timeout`，但 PayNova 服务端仍在继续处理并最终扣款成功。`v2.14.0` 移除了超时后的状态查询（`status_check_on_timeout=false`），改为直接重试最多 3 次（`max_attempts=3`），且**每次重试都生成了全新的 `idempotency_key`**。由于不同幂等键在 PayNova 侧视为独立扣款，超时后仍在进行的原请求与重试请求双双入账，甚至出现同一订单被扣款 2–3 次、或后续重试 `declined`/`timeout` 导致订单状态为 `payment_failed` 但前序超时尝试已实际扣款的情况。
2. **为何之前/之后版本无此问题**：
   - 回滚前的 `v2.13.4`（及回滚后 `DEP-7740`）配置 `retry_on_timeout=false, max_attempts=1, status_check_on_timeout=true`，在 `3000 ms` 超时后仅调用 `charge.status_check` 反查 PayNova 结果，不会发起重复扣款请求。
   - 后续修复版 `v2.14.2`（`DEP-7752`）在开启超时重试的同时复用了同一 `idempotency_key`，利用 PayNova 的幂等保证避免重复入账。
3. **为何网关 502 激增**：`gateway` 对 `/api/v2/checkout` 的 `proxy_read_timeout` 为 `8 s`。`v2.14.0` 发生连续 2–3 次 `3000 ms` 超时加退避等待（单次退避约 200–500 ms）时，上游总耗时突破 8 秒（如 3 次超时约 9.5–10 秒），网关以 `502 (rt=8.000)` 断连返回，而后端仍继续执行扣款。

## 2. 关键证据

1. **`v2.14.0` 超时后更换 `idem_key` 重试导致重复扣款（首笔事故多扣 `O0314-003221`）**：
   - `payment-svc.log`：
     - `2026-03-14T06:40:39.501Z INFO  [payment-svc v2.14.0] event=charge.request order=O0314-003221 attempt=1 idem_key=pi_e63defb623db13bac408 amount=14950 currency=CNY trace=35916bc85e5cd9f0`
     - `2026-03-14T06:40:42.501Z WARN  [payment-svc v2.14.0] event=charge.result order=O0314-003221 attempt=1 idem_key=pi_e63defb623db13bac408 result=timeout duration_ms=3000 trace=35916bc85e5cd9f0`
     - `2026-03-14T06:40:42.766Z INFO  [payment-svc v2.14.0] event=charge.request order=O0314-003221 attempt=2 idem_key=pi_220fcea2cd9e0cdda14d amount=14950 currency=CNY trace=35916bc85e5cd9f0`
   - `provider_charges.csv` 显示同一订单 `O0314-003221` 存在两笔 `succeeded` 扣款：`ch_9dd7d5c265b7ebfa`（`2026-03-14T06:40:43Z`）与 `ch_f3c69d1fae2b8a3a`（`2026-03-14T06:40:44Z`）。
2. **`payment_failed` 订单仍被扣款 3 次且网关超时 502（`O0314-004068`）**：
   - `payment-svc.log` 中 `O0314-004068`（`trace=0f14a36b2eeef1a8`）三次尝试分别使用 `pi_86f5370445945ab08a17`、`pi_f6c2ad411061235d8c0f`、`pi_a5081d5e95d7e769f2d9`，均在 `3000 ms` 时 `result=timeout`；`order-svc.jsonl` 在 `08:01:13.276Z` 记录 `order.payment_failed`（`reason=provider_timeout`）；`gateway-access.log` 在 `16:01:11 CST`（`08:01:11Z`）记录 `502 rt=8.000`；但 `provider_charges.csv` 中三笔均 `succeeded`。
3. **版本配置与超时率指标变化**：
   - `payment-svc.log`：`2026-03-14T06:39:55.000Z` 加载 `v2.14.0` 配置 `retry_on_timeout=true max_attempts=3 status_check_on_timeout=false`；回滚后 `08:02:25.000Z` 恢复为 `retry_on_timeout=false max_attempts=1 status_check_on_timeout=true`。
   - 事故窗口 `[06:40:00Z, 08:02:30Z)` 内 `charge.result` 共 1254 条，其中 `timeout` 400 条（`31.9%`），p95 耗时由前两小时的 `2456 ms` 升至 `3000 ms`。
4. **财务影响汇总**：全量数据中共 `141` 笔订单存在未退还超额扣款（`outstanding refund > 0`），合计 `CNY 6264430 分`、`USD 247978 美分`；影响最大用户为 `U100670`（订单 `O0314-003351` 失败但成功扣款两笔各 64500 美分，折合 `915900` 人民币分）。

## 3. 时间线（UTC）

- **03:12:21Z**：非本次事故的偶发并发重复扣款 `O0314-001701`（两笔独立请求间隔 29ms），已于 `03:33:21Z` 人工退款。
- **06:30:00Z**：PayNova `cn-east` 区域延迟升高；`v2.13.4` 通过 `charge.status_check` 正常反查，未发生重复扣款，网关 `06:30–06:40Z` 无 502。
- **06:33:20Z**：`DEP-7729`（`gateway cfg-0314a`）发布完成，调整 `keepalive_timeout`。
- **06:36:10Z – 06:40:00Z**：`DEP-7731` 发布 `payment-svc v2.14.0`。
- **06:40:44Z**：发布后首笔 extra charge 产生（订单 `O0314-003221` 的 `ch_f3c69d1fae2b8a3a`）。
- **07:08:00Z – 07:12:40Z**：`DEP-7735` 发布 `order-svc v3.9.0`。
- **07:58:40Z – 08:02:30Z**：`DEP-7740` 将 `payment-svc` 回滚至 `v2.13.4`；在途请求 `O0314-004083`（`08:02:25Z` 发起）于 `08:02:30Z` 产生最后一笔多扣（后续已人工退款），此后停止。
- **08:31:00Z**：PayNova 延迟恢复正常。
- **15:30:00Z – 15:34:00Z**：`DEP-7752` 发布 `payment-svc v2.14.2`，修复为超时重试复用同一 `idempotency_key`。

## 4. 排除的误导线索

- **`DEP-7729`（gateway `keepalive_timeout` 65s -> 30s）**：Slack 中猜测其导致 502，但 nginx 日志为 UTC+8（`14:33 CST = 06:33Z`），发布后至 `06:40Z` 之间 502 为 0；所有窗口内 88 次 checkout 502 均精确发生在 `rt=8.000`（`proxy_read_timeout`），与客户端 keepalive 无关。
- **Split payment（礼品卡+银行卡组合支付）**：全量 353 笔 `split` 订单中，成功扣款总额与应付金额全部一致（`succ != owed` 为 0 笔），均使用 `_gc` 与 `_card` 两个独立幂等键，非重复扣款。
- **`DEP-7735`（`order-svc v3.9.0`，`07:08–07:12:40Z`）**：首笔事故多扣早在 `06:40:44Z` 即已发生，早于 `DEP-7735` 近半小时，排除其为主因。
- **前置孤立多扣 `O0314-001701`（`03:12:21Z`）**：发生在 `v2.13.4` 期间且非超时重试（两笔不同 trace 并发请求），且已于 `03:33:21Z` 全额退回，不计入本次故障引入的未退金额。
- **网关 `GET /api/v2/search` 的 1 条 502（`15:40:29 CST`）**：上游为 `catalog-svc`（`rt=0.021`），与结算接口无关。

## 5. 修复与预防建议

1. **立即对账退款**：基于 `orders.csv` 与 `provider_charges.csv` 按财务口径全量导出 141 笔待退订单清单并执行退款（尤其注意 `status=payment_failed` 但渠道侧 `succeeded` 的隐蔽多扣订单）。
2. **强制幂等与超时协同**：任何跨次重试必须绑定并复用同一支付意图的 `idempotency_key`（如 `v2.14.2`），并在客户端超时后结合 `status_check` 核实渠道状态。
3. **统一超时预算对齐**：单次调用超时（3s）× 最大重试次数 + 退避时间（约 10s）必须小于网关 `proxy_read_timeout`（8s），否则应调小下游重试预算或改用异步支付状态确认，避免网关断连后后台继续扣款。
4. **可观测性改进**：统一所有服务日志时区（建议网关接入也记录 ISO-8601 UTC 或显式时区偏移），对“订单失败但渠道扣款成功”及单订单多笔成功扣款建立实时对账告警。
