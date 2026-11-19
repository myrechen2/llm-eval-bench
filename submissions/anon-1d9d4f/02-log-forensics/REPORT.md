# ShopFast 2026-03-14 支付重复扣款与 502 事故复盘报告

## 1. 事故概述与影响

2026-03-14 06:40:00Z 至 08:02:30Z 期间，ShopFast 结账接口出现大面积 502（窗口内 `POST /api/v2/checkout` 共 **88** 次）及用户重复扣款（全量共产生 **237** 笔事故期超额扣款；扣除客服已手动退款的 53 笔及事故前 1 笔已退款记录，目前仍有 **141** 笔订单待退款，包括 102 笔 `paid` 订单和 39 笔 `payment_failed` 订单，待退总额 **CNY 62,644.30**（6,264,430 分）与 **USD 2,479.78**（247,978 美分），单用户最高待退为 `U100670` 的折合人民币 **9,159.00 元**）。

## 2. 根因分析

事故由**外部渠道延迟升高**与 **`payment-svc v2.14.0`（`DEP-7731`）超时重试幂等键缺陷**共同触发：

1. **直接触发条件**：PayNova `cn-east` 扣款接口自 06:30Z 起出现延迟抖动（`payment-svc` 窗口内 `charge.result` p95 升至客户端超时上限 **3000 ms**，超时率达 **31.9%**），但超时请求在 PayNova 侧仍在继续处理并完成扣款。
2. **重复扣款机制**：`payment-svc v2.14.0` 移除了旧版 `status_check` 状态轮询路径，改为超时自动重试（最多 3 次）。但每次重试都**重新生成了新的 `idem_key`**，而非复用原支付意图的幂等键。PayNova 仅对相同幂等键去重，因此每次超时重试都被渠道当作一笔全新独立扣款执行，导致单笔订单被扣款 2–3 次；若最终一次重试被拒付，订单还会被标为 `payment_failed`（客户应付为 0），造成已成功扣款全部成为超额扣款。
3. **网关 502 机制**：单次扣款超时 3 s，连续重试 2–3 次叠加退避耗时超过 8 s，触发网关 `proxy_read_timeout = 8s` 返回 502，而后端 `order-svc`/`payment-svc` 仍在后台完成扣款。
4. **为何此前/此后版本无此问题**：
   * `v2.13.4`（`DEP-7731` 之前及 `DEP-7740` 回滚之后）在超时后调用 `event=charge.status_check` 按原 `idem_key` 查询状态，不发起新扣款；
   * `v2.14.2`（`DEP-7752`）修复了重试逻辑，超时重试复用同一个 `idem_key`，由 PayNova 侧保证幂等。

## 3. 关键证据

1. **首笔事故期超额扣款（`O0314-003221`，`payment-svc.log` 与 `provider_charges.csv`）**：
   * `2026-03-14T06:40:39.501Z INFO [payment-svc v2.14.0] event=charge.request order=O0314-003221 attempt=1 idem_key=pi_e63defb623db13bac408 amount=14950 currency=CNY trace=35916bc85e5cd9f0`（3000 ms 超时，但 PayNova 于 `06:40:43Z` 成功入账 `ch_9dd7d5c265b7ebfa`）
   * `2026-03-14T06:40:42.766Z INFO [payment-svc v2.14.0] event=charge.request order=O0314-003221 attempt=2 idem_key=pi_220fcea2cd9e0cdda14d amount=14950 currency=CNY trace=35916bc85e5cd9f0`（更换了 `idem_key`，于 `06:40:44Z` 再次成功入账 `ch_f3c69d1fae2b8a3a`）
2. **重试拖垮网关并导致 `payment_failed` 订单被双扣（`O0314-003351`，用户 `U100670`，`trace=7f9430e64538abec`）**：
   * `payment-svc.log` 中 `attempt=1/2/3` 分别使用 `pi_0ae2a3da67b09c49cb76`、`pi_adc17b241b49c74ac005`、`pi_c6a5a4cbfc1cf98c6475` 三个不同幂等键，前两次超时但在 PayNova 各扣款 USD 645.00，第三次于 `06:53:13.141Z` 返回 `declined`；
   * `gateway-access.log`：`10.36.199.186 - U100670 [14/Mar/2026:14:53:12] "POST /api/v2/checkout HTTP/1.1" 502 rt=8.000 upstream=order-svc trace=7f9430e64538abec`（CST 14:53:12 = UTC 06:53:12）；
   * `order-svc.jsonl` 于 `06:53:13.177Z` 记录 `order.payment_failed`，最终用户净多扣 USD 1,290.00。
3. **旧版 `v2.13.4` 在 PayNova 慢响应期间未产生重复扣款（`O0314-003126`）**：
   * `2026-03-14T06:30:15.337Z WARN [payment-svc v2.13.4] event=charge.result order=O0314-003126 attempt=1 idem_key=pi_ff013f566d8dea2d4a05 result=timeout duration_ms=3000`
   * `2026-03-14T06:30:15.616Z WARN [payment-svc v2.13.4] event=charge.status_check order=O0314-003126 idem_key=pi_ff013f566d8dea2d4a05 found=false`

## 4. 事故时间线（UTC）

| 时间 (UTC) | 事件 |
|---|---|
| 06:30:00Z | PayNova `cn-east` 扣款 API 延迟开始升高（CST 14:30） |
| 06:33:20Z | `DEP-7729`：gateway 调整 `keepalive_timeout`（无关） |
| 06:36:10Z–06:40:00Z | **`DEP-7731`**：`payment-svc v2.14.0` 发布上线（引入超时重试换新幂等键缺陷） |
| 06:40:44Z | 出现首笔事故期超额扣款（`O0314-003221` / `ch_f3c69d1fae2b8a3a`） |
| 06:44:00Z | SRE 告警网关 checkout 502 上升（CST 14:44） |
| 07:05:00Z | 客服反馈用户被重复扣款（CST 15:05） |
| 07:08:00Z–07:12:40Z | `DEP-7735`：`order-svc v3.9.0` 发布（无关） |
| 07:58:40Z–08:02:30Z | **`DEP-7740`**：`payment-svc` 回滚至 `v2.13.4`，超额扣款与 502 随即停止 |
| 08:31:00Z | PayNova 延迟恢复正常（CST 16:31） |
| 15:30:00Z–15:34:00Z | `DEP-7752`：`payment-svc v2.14.2` 上线，修复为重试复用幂等键 |

## 5. 排除的误导线索

* **`DEP-7729`（gateway keepalive 变更）**：仅调整客户端侧 `keepalive_timeout`（65s→30s），未改动上游配置；且网关 502 的 `rt=8.000` 明确为上游读超时，并非连接关闭。
* **拆单支付（split payments）**：礼品卡 + 银行卡拆单的两笔扣款之和严格等于订单金额（如 `O0313-000010`：1780 + 7120 = 8900），全部 141 笔待退订单均为 `card` 单一支付方式，无一例由拆单导致。
* **`DEP-7735`（`order-svc v3.9.0` 发布）**：07:08Z 才开始发布，而重复扣款早在 06:40:44Z 即已开始。
* **网关日志时区陷阱与盘前 502**：`gateway-access.log` 使用无时区偏移的 CST（UTC+8），`14/Mar/2026:06:40..08:00` 实际对应 `2026-03-13T22:40Z..00:00Z`（早间另一次波动），而非本次事故窗口。

## 6. 修复与预防建议

1. **强约束幂等键生命周期**：将幂等键与订单/支付意图（PaymentIntent）持久化绑定，禁止在重试层随机生成新键；在集成测试中增加“渠道超时后重试”的幂等性自动化校验。
2. **全链路超时预算对齐**：`payment-svc` 重试总耗时上限（含 backoff）必须严格小于上游 `order-svc` 及网关 `proxy_read_timeout`（8 s），避免客户端收到 502 而后端仍在扣款。
3. **自动对账与告警**：建立定时对账任务，监控“单订单成功扣款总额 > 订单应付金额”以及“`payment_failed` 订单存在 `succeeded` 扣款”异常，触发即时告警并自动阻断发布。
4. **日志时区统一**：将 nginx 网关日志统一改为带时区偏移的 ISO-8601 UTC 格式，消除跨服务排障时的时区错位风险。
