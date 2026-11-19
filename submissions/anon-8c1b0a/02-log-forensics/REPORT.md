# ShopFast 2026-03-14 支付重复扣款与网关 502 事故复盘报告

## 1. 根因分析（机制与触发条件）

本次事故由 **外部渠道 PayNova 延迟升高（触发条件）** 与 **`payment-svc v2.14.0`（`DEP-7731`）超时重试未复用幂等键的缺陷（直接根因）** 共同导致：

1. **为什么会重复扣款与触发 502**：
   * 2026-03-14 06:30 UTC 起，支付渠道 PayNova 的 `POST /v3/charges` 接口出现高延迟（大量请求耗时超过 `payment-svc` 的 `3000 ms` 客户端超时阈值，但仍在 PayNova 后台继续处理并最终成功扣款）。
   * 06:40:00 UTC 完成发布的 `payment-svc v2.14.0`（`DEP-7731`）将超时处理逻辑由状态轮询（`status_check_on_timeout`）改为直接重试扣款（`retry_on_timeout=true, max_attempts=3, status_check_on_timeout=false`），但**每次重试都重新生成了新的 `idem_key`（幂等键）**。由于 PayNova 仅对相同幂等键保证单次扣款、对不同幂等键视为独立扣款请求，当第 1 次（甚至第 2 次）请求在客户端 `3000 ms` 超时但在 PayNova 侧实际成功时，携带新 `idem_key` 的重试会触发第 2、第 3 笔真实扣款。
   * 此外，需要特别注意两类隐蔽的超额扣款：一是部分 `paid` 订单被成功扣款 3 次，客服仅按"双倍扣款"人工退了 1 笔，仍欠退 1 笔（共 5 单）；二是当 3 次尝试在客户端均超时（或前几次超时但后台成功、第 3 次被拒付）时，`order-svc` 将订单标记为 `payment_failed`（客户应付 `owed = 0`），但 PayNova 侧实际已成功扣款 1～3 笔（共 39 单）。
   * 当一笔订单发生 2 次超时并进入第 3 次尝试时，单次结账总耗时（`3000 ms + backoff + 3000 ms + backoff + attempt3`）超过网关 `proxy_read_timeout = 8 s`，导致网关在 `rt=8.000` 秒断开并返回 `502`（事故窗口内共 88 次）。
2. **为什么之前与之后的版本没有问题**：
   * **之前的 `v2.13.4`（及回滚 `DEP-7740`）**：`retry_on_timeout=false, max_attempts=1, status_check_on_timeout=true`。遇到 `3000 ms` 超时后不会发起新扣款，而是用原 `idem_key` 执行 `event=charge.status_check` 查询结果，最多只产生 1 笔扣款，且总耗时约 3.2 秒，远低于网关 8 秒超时。
   * **之后的 `v2.14.2`（`DEP-7752`）**：修复了重试逻辑，在超时重试时**复用同一 payment intent 的 `idem_key`**，由 PayNova 的幂等保障确保多次重试最多只创建一笔扣款。

---

## 2. 关键证据

1. **配置变更与版本对比（`payment-svc.log`）**：
   * `2026-03-14T06:39:55.000Z INFO [payment-svc v2.14.0] event=config.loaded provider_timeout_ms=3000 retry_on_timeout=true max_attempts=3 status_check_on_timeout=false`
   * `2026-03-14T08:02:25.000Z INFO [payment-svc v2.13.4] event=config.loaded provider_timeout_ms=3000 retry_on_timeout=false max_attempts=1 status_check_on_timeout=true`
   * `v2.13.4` 在 PayNova 高延迟期间（如 `06:30:26Z` 订单 `O0314-003128`）超时后通过 `event=charge.status_check order=O0314-003128 idem_key=pi_e10719915073ae948443 found=true charge_id=ch_ea84195e13c43eb8` 确认扣款成功，未产生任何重复扣款。
2. **`v2.14.0` 首笔事故重复扣款（订单 `O0314-003221`，`trace=35916bc85e5cd9f0`）**：
   * `06:40:39.501Z` `attempt=1` 使用 `idem_key=pi_e63defb623db13bac408`，`06:40:42.501Z` 客户端 `3000 ms` 超时；但 `provider_charges.csv` 显示该幂等键在 `2026-03-14T06:40:43Z` 成功生成扣款 `ch_9dd7d5c265b7ebfa`（`14950` 分）。
   * `06:40:42.766Z` `attempt=2` 更换了新幂等键 `idem_key=pi_220fcea2cd9e0cdda14d`，于 `2026-03-14T06:40:44Z` 再次成功生成扣款 `ch_f3c69d1fae2b8a3a`（`14950` 分），造成同一订单被扣款两次。
3. **3 次尝试引发网关 `rt=8.000` 的 502 及 `payment_failed` 隐形扣款（如 `O0314-003220`、`O0314-003251`、`O0314-003351`）**：
   * `O0314-003220`（`trace=5e0db11429cff095`）：`06:40:37.537Z` 发起，`attempt=1`、`attempt=2` 均 `3000 ms` 超时，`attempt=3` 于 `06:40:46.383Z` 完成（总耗时 `8.85 s > 8 s`），网关日志记录 `[14/Mar/2026:14:40:45] "POST /api/v2/checkout HTTP/1.1" 502 rt=8.000 upstream=order-svc trace=5e0db11429cff095`（UTC `06:40:45Z`）。
   * `O0314-003351`（用户 `U100670`，金额 `64500` USD cents）：`attempt=1`（`pi_0ae2a3da67b09c49cb76`）和 `attempt=2`（`pi_adc17b241b49c74ac005`）均超时但 PayNova 侧均扣款成功（共 `129000` USD cents，折合 `915900` CNY 分）；`attempt=3`（`pi_c6a5a4cbfc1cf98c6475`）被拒付（`card_declined`），导致订单状态为 `payment_failed`（`owed=0`），但用户实际被扣两笔共 `$1,290.00`。

---

## 3. 事故时间线（统一使用 UTC）

* **2026-03-14 06:30:00Z**：PayNova `POST /v3/charges` 接口延迟开始升高（`payment-svc` 超时率上升，但当时运行的 `v2.13.4` 通过 `status_check` 处理，未产生重复扣款）。
* **2026-03-14 06:31:00Z – 06:33:20Z**：网关发布 `DEP-7729`（`cfg-0314a`，调整 `keepalive_timeout`），与本次事故无关。
* **2026-03-14 06:36:10Z – 06:40:00Z**：**致因发布 `DEP-7731`**（`payment-svc v2.14.0`）上线，开启超时重试且每次生成新幂等键，同时网关 8 秒超时 502 开始激增。
* **2026-03-14 06:40:44Z**：产生事故窗口内第一笔 extra charge（订单 `O0314-003221`，`ch_f3c69d1fae2b8a3a`）。
* **2026-03-14 06:44:00Z – 07:41:00Z**：SRE 发现网关 502 激增、客服收到重复扣款反馈，团队排查网关 keepalive、PayNova 状态页并定位到 `payment-svc v2.14.0`。
* **2026-03-14 07:58:40Z – 08:02:30Z**：**止损发布 `DEP-7740`** 将 `payment-svc` 回滚至 `v2.13.4`。最后一笔 extra charge 发生在 `08:02:30Z`（订单 `O0314-004083`），此后重复扣款与 8 秒超时 502 完全停止。
* **2026-03-14 08:25:00Z**：客服开始对部分明显重复扣款的订单进行人工退款（未覆盖第 3 次扣款及 `payment_failed` 订单）。
* **2026-03-14 08:31:00Z**：PayNova 接口延迟恢复正常。
* **2026-03-14 15:30:00Z – 15:34:00Z**：发布 `DEP-7752`（`payment-svc v2.14.2`），修复为超时重试复用同一幂等键。

---

## 4. 排除的误导线索及依据

1. **误导 1：网关 `DEP-7729`（06:33:20Z 修改 `keepalive_timeout`）导致 502**
   * **排除依据**：网关日志是 `Asia/Shanghai (UTC+8)` 时区。`[06:40:00Z, 08:02:30Z)` 窗口内的 88 条结账 502 响应时间全部为 `rt=8.000`（命中 `proxy_read_timeout = 8s`），是因为 `payment-svc v2.14.0` 最多 3 次 `3000 ms` 尝试总耗时超过 8 秒；而在 `[06:33:20Z, 06:40:00Z)`（即 `DEP-7729` 完成到 `DEP-7731` 完成之间）网关结账 502 数量为 **0**。（另注：网关日志中本地时间 `06:40–08:02 CST` 即 `2026-03-13 22:40–00:02 UTC` 有少量 `rt < 1.5s` 的常规 502，若混淆时区会误判。）
2. **误导 2：重复扣款只是组合支付（Split Payment：礼品卡 + 银行卡）**
   * **排除依据**：组合支付使用 `pi_<order>_gc` 与 `pi_<order>_card` 两个幂等键，两笔扣款金额之和等于订单 `amount_minor`（`outstanding_refund = 0`）。而事故受影响的全部 141 笔待退款订单均为 `payment_method = card`，每笔扣款均为订单全额。
3. **误导 3：`order-svc v3.9.0`（`DEP-7735`，07:08:00Z–07:12:40Z）或事故前的单笔重复扣款 `O0314-001701`**
   * **排除依据**：重复扣款在 `06:40:44Z` 即已开始，早于 `DEP-7735` 近 28 分钟；而 `03:12:21Z` 的订单 `O0314-001701` 在 `payment-svc.log` 中有两条不同的 `trace`（`cc641718f57fa6b1` 与 `adda254f1cc399f9`）同时发起 `attempt=1`，属于偶发的上游并发重复请求且已于 `03:33:21Z` 人工全额退款（`ch_d20d53d24a903332`），并非下午批量事故的根因。

---

## 5. 修复与预防建议

1. **财务精准退款**：按对账规则对全部 **141 笔** `outstanding_refund > 0` 的订单执行退款（总计 **CNY 6,264,430 分**、**USD 247,978 美分**），特别包含 39 笔状态为 `payment_failed` 但实际已扣款的订单，以及 5 笔被扣 3 次仅退了 1 次的 `paid` 订单。
2. **端到端确定性幂等键**：`payment-svc` 应基于 `(order_id, payment_leg)` 派生确定性的幂等键（而非每次请求/重试随机生成），从架构上杜绝同一支付意图产生不同幂等键。
3. **超时预算对齐与异步对账**：网关 `proxy_read_timeout`（8s）应大于下游最大重试总耗时（`3 * 3000ms + backoff > 9s`），并在 `payment_failed` 落库后增加与渠道侧的自动定时对账/冲正任务，防止超时成功单成为漏网的隐形扣款。
