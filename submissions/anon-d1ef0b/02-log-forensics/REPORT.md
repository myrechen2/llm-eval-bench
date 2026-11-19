# ShopFast 2026-03-14 支付重复扣款与 502 事故复盘报告

## 1. 事故概述与影响范围

2026-03-14 `06:40:00Z`–`08:02:30Z`(CST 14:40–16:02),ShopFast 结账链路发生支付重复扣款与网关 `502` 激增事故:

* 窗口内 `POST /api/v2/checkout` 产生 **88** 次网关 `502`;`payment-svc` 调用 PayNova 的超时率升至 **31.9%**(`400 / 1254`),`charge.result` p95 耗时从事故前 2 小时的 **2456 ms** 攀升至超时上限 **3000 ms**。
* 共产生 **237** 笔事故相关 extra charge(涉及 188 笔订单)。客服已人工退回 52 笔(另有事故前 03:12Z 的 1 笔无关重复扣款 `O0314-001701` 已退款),当前仍有 **141** 笔订单存在未退余额(其中 `paid` 订单 102 笔、`payment_failed` 订单 39 笔),待退总额 **CNY 6,264,430 分(¥62,644.30)** 与 **USD 247,978 美分($2,479.78)**。
* 受影响最严重用户为 `U100670`:其 `payment_failed` 订单 `O0314-003351` 被成功扣款两次(各 $645.00),待退 $1,290.00,按 1 USD = 7.10 CNY 折合 **915,900 分(¥9,159.00)**。

## 2. 根因分析

本次事故由 **PayNova 渠道延迟升高**(触发条件)与 **`payment-svc v2.14.0`(DEP-7731) 重试未复用幂等键**(直接缺陷)叠加导致:

1. **重复扣款机制**:`DEP-7731` 将超时处理策略从"查单(`status_check_on_timeout=true`, `max_attempts=1`)"改为"自动重试(`retry_on_timeout=true`, `max_attempts=3`, `status_check_on_timeout=false`)",但在生成第 2/3 次重试请求时**每次都重新生成了新的随机 `idem_key`**。
2. **触发条件**:自 `06:30Z`(14:30 CST)起 PayNova `cn-east` 区域延迟升高,部分扣款请求超过 `payment-svc` 的 **3000 ms** 客户端超时,但 PayNova 侧仍在继续处理并最终扣款成功。`v2.14.0` 超时后使用**不同** `idem_key` 重试,PayNova 将每次重试视为独立扣款,导致单笔订单产生 2–3 笔成功扣款;若后续重试失败或全部超时,订单被标记为 `payment_failed`(用户应付 0),但此前超时的请求在 PayNova 已成功扣款,形成 39 笔"失败订单被扣款"的隐蔽资损。
3. **网关 502 机制**:多次 3000 ms 超时叠加退避延迟(如 3 次尝试合计 > 8 s)触发 nginx `proxy_read_timeout` (8 s),网关返回 `502` 但后端继续完成扣款。
4. **为何前后版本无此问题**:
   * **回滚前/后的 `v2.13.4`**:超时后不重试,而是携带原 `idem_key` 执行 `charge.status_check` 确认渠道侧结果(日志可见 `found=true` 69 次、`found=false` 56 次),即使 PayNova 持续高延迟(06:30–06:40Z 及 08:02–08:31Z)也未产生重复扣款。
   * **修复版本 `v2.14.2`(DEP-7752)**:重新启用超时重试的同时严格复用同一 payment intent 的 `idem_key`,由 PayNova 保证幂等。

## 3. 关键证据

1. **版本配置切换(`payment-svc.log` L6859 / L9774)**:
   * `2026-03-14T06:39:55.000Z INFO [payment-svc v2.14.0] event=config.loaded provider_timeout_ms=3000 retry_on_timeout=true max_attempts=3 status_check_on_timeout=false`
   * `2026-03-14T08:02:25.000Z INFO [payment-svc v2.13.4] event=config.loaded provider_timeout_ms=3000 retry_on_timeout=false max_attempts=1 status_check_on_timeout=true`
2. **首笔事故 extra charge 完整链路(`O0314-003221`, trace `35916bc85e5cd9f0`)**:
   * `payment-svc.log` L6879/L6883/L6885/L6889:attempt=1 使用 `idem_key=pi_e63defb623db13bac408` 于 `06:40:42.501Z` 超时(3000 ms);attempt=2 换用新键 `idem_key=pi_220fcea2cd9e0cdda14d` 于 `06:40:44.812Z` 成功(`ch_f3c69d1fae2b8a3a`)。
   * `provider_charges.csv`:PayNova 对该订单落账两笔 `succeeded`(各 14950 CNY):`ch_9dd7d5c265b7ebfa`(`06:40:43Z`,对应 attempt=1)与 `ch_f3c69d1fae2b8a3a`(`06:40:44Z`,对应 attempt=2,即首笔 extra charge)。
3. **超时重试触发网关 502 与重扣(`O0314-003220`, trace `5e0db11429cff095`)**:
   * `payment-svc.log` L6878–L6890:3 次尝试分别使用 3 个不同 `idem_key`(`pi_f21bf...`、`pi_1b2ce...`、`pi_545af...`),前两次 3000 ms 超时,第 3 次于 `06:40:46.383Z` 成功;PayNova 实际成功扣款两笔(`ch_e23820c81f397fab` 与 `ch_cbfba4b6b9ed90d1`,各 129900 CNY)。
   * `gateway-access.log` L25680:`[14/Mar/2026:14:40:45]`(即 `06:40:45Z`)返回 `502 rt=8.000 upstream=order-svc`。
4. **失败订单被重复扣款(`O0314-003351`, 用户 `U100670`)**:
   * `orders.csv` 中订单状态为 `payment_failed`(amount 64500 USD),而 `provider_charges.csv` 记录了两笔 `succeeded` 扣款(`ch_63aa0c4722dda1ad` 与 `ch_ae357fb38500077d`,不同 `idem_key`),合计 129000 USD 美分未退。

## 4. 事故时间线(UTC)

* `03:12:21Z`:无关事件 `O0314-001701` 因并发请求产生 1 笔重复扣款,已于 `03:33:21Z` 人工退款。
* `06:30:00Z`(14:30 CST):PayNova `cn-east` 延迟升高;`payment-svc v2.13.4` 通过 `status_check` 兜底,无重复扣款。
* `06:33:20Z`:`DEP-7729` 发布网关 keepalive 配置变更(无关)。
* `06:36:10Z`–`06:40:00Z`:`DEP-7731` 发布 **`payment-svc v2.14.0`**(根因发布)。
* `06:40:44Z`:事故窗口内首笔 extra charge 产生(`O0314-003221`, `ch_f3c69d1fae2b8a3a`),随后网关 502 与重复扣款持续发生。
* `07:08:00Z`–`07:12:40Z`:`DEP-7735` 发布 `order-svc v3.9.0`(无关)。
* `07:58:40Z`–`08:02:30Z`:`DEP-7740` 将 `payment-svc` **回滚至 `v2.13.4`**(止血发布);仅 1 笔在回滚前已发出的在途重试(`O0314-004083`)于 `08:02:30Z` 完成扣款(后已退款),此后重复扣款彻底停止。
* `08:31:00Z`(16:31 CST):PayNova 延迟恢复正常。
* `15:30:00Z`–`15:34:00Z`:`DEP-7752` 发布 `payment-svc v2.14.2`,修复重试复用幂等键问题。

## 5. 排除的误导线索

1. **网关 keepalive 变更(`DEP-7729`, `06:33:20Z`)**:仅将 `keepalive_timeout` 从 65s 调为 30s,未改动上游超时;且 `06:33:20Z`–`06:40:00Z` 间 `checkout` 无 502 飙升,502 均在 `06:40Z` 后伴随 `rt=8.000` 出现,与上游读超时直接吻合。
2. **拆分支付(`split`: gift card + card)**:全量 353 笔 `split` 订单中,所有成功扣款之和与订单应收金额误差为 **0**,141 笔待退订单全部为 `card` 支付,并非拆分支付误报。
3. **`order-svc v3.9.0` 发布(`DEP-7735`, `07:08Z`–`07:12:40Z`)**:在该发布完成前已累计产生 **88** 笔事故 extra charge,发布仅涉及缓存预热与优惠券校验,并非诱因。
4. **网关日志时区陷阱**:nginx 日志无时区偏移且为 CST(UTC+8);其在 `[14/Mar/2026:06:40–08:02]` 存在一批 60 次 `checkout` 502,实为前一日 `22:40Z–00:02Z` 的历史波动,与本次事故无关。
5. **客服人工退款口径遗漏**:客服仅排查了显性的 `paid` 双扣订单(退回 53 笔),完全遗漏了 39 笔 `payment_failed` 却在渠道成功扣款的订单。

## 6. 修复与预防建议

1. **幂等键与订单/支付意图强绑定**:由 `order_id` + 支付意图维度持久化生成 `idem_key`,禁止在重试循环内重新生成;在单测与集成测试中强制校验"模拟超时重试后多次请求 `idem_key` 恒等"。
2. **超时预算分级与熔断**:下游单次超时 × 最大重试次数 + 退避必须严格小于网关 `proxy_read_timeout`(8 s),防止网关提前 502 而后端继续扣款。
3. **保留超时查单与自动化日终对账**:重试耗尽后执行 `status_check` 同步最终状态;建立 `orders.csv` 与 PayNova 结算单的准实时自动对账告警,显式覆盖 `payment_failed`/`cancelled` 订单的"渠道已扣款"场景并自动生成退款工单。
4. **统一日志时区**:将 nginx 网关日志统一为带时区偏移的 ISO-8601 UTC 格式,消除跨服务排障时区换算风险。
