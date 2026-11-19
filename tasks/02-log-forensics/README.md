# 任务 02 · 线上事故日志取证(Terminal / 长上下文 / 数据分析类)

**对标:** Terminal-Bench 2.x(在终端中完成真实运维/数据任务)、MRCR / 长上下文多跳检索、DABstep 类数据分析。考察:在 ~30 MB 多源异构数据中定位证据、处理时区与口径陷阱、跨数据源关联、精确计算,并写出可信的根因分析。

## 背景

电商平台 ShopFast 在 2026-03-14 下午发生了支付事故:网关 502 增多、用户反馈被重复扣款。你是事后复盘的工程师。财务明天要拿到**精确**的退款名单和金额。

## 数据(`data/`,只读)

| 文件 | 说明 |
|---|---|
| `logs/gateway-access.log` | nginx 访问日志(约 11.5 万行)|
| `logs/order-svc.jsonl` | 订单服务 JSON 日志 |
| `logs/payment-svc.log` | 支付服务 key=value 日志 |
| `orders.csv` | 订单导出 |
| `provider_charges.csv` | 支付渠道 PayNova 的扣款结算导出 |
| `deploys.csv` | 当天所有发布记录 |
| `docs/*.md` | 架构说明、财务对账口径、渠道状态页、事故频道聊天记录 |

**`docs/` 里的口径定义是权威的**;聊天记录里的说法不一定正确。

## 问题

把答案写入 `submissions/<SUBMISSION_ID>/02-log-forensics/answers.json`,严格使用下面的键名和类型:

```json
{
  "culprit_deploy_id": "DEP-xxxx",
  "mitigation_deploy_id": "DEP-xxxx",
  "first_extra_charge_utc": "2026-03-14THH:MM:SSZ",
  "orders_needing_refund": 0,
  "outstanding_refund_minor": {"CNY": 0, "USD": 0},
  "top_user": {"user_id": "Uxxxxxx", "outstanding_cny_minor": 0},
  "gateway_checkout_502_in_window": 0,
  "charge_result_stats": {
    "before_p95_ms": 0,
    "during_p95_ms": 0,
    "during_timeout_rate_pct": 0.0
  }
}
```

1. **`culprit_deploy_id`** —— 引入"重复扣款"问题的那次发布。
2. **`mitigation_deploy_id`** —— 让重复扣款停止的那次发布。
3. **`first_extra_charge_utc`** —— 在 culprit 发布的 `finished_at_utc` 之后(含),第一笔 *extra charge*(定义见 `docs/finance-reconciliation.md`)的 `created_at_utc`。
4. **`orders_needing_refund`** —— 当前 *outstanding refund* > 0 的订单数(全量数据,不限时间)。
5. **`outstanding_refund_minor`** —— 按币种汇总的 outstanding refund 总额(最小货币单位,整数)。
6. **`top_user`** —— outstanding refund 折合人民币(按文档汇率)最多的用户,以及该用户的折合金额(人民币分,四舍五入到整数)。
7. **`gateway_checkout_502_in_window`** —— 网关日志中 `POST /api/v2/checkout` 且状态码为 502 的请求数,时间窗口为 **[culprit 的 `finished_at_utc`, mitigation 的 `finished_at_utc`)**,按日志行时间戳(注意时区)判断。
8. **`charge_result_stats`** —— 基于 payment-svc 日志中**所有** `event=charge.result` 行(含超时、拒付,不论第几次尝试)的 `duration_ms`:
   * `before_p95_ms`:窗口 [culprit finished − 2h, culprit finished) 内的 p95;
   * `during_p95_ms`:窗口 [culprit finished, mitigation finished) 内的 p95;
   * `during_timeout_rate_pct`:后一窗口内 `result=timeout` 行占比,百分数保留 1 位小数。
   * p95 使用 nearest-rank 法:升序排序后取第 ⌈0.95·n⌉ 个值(从 1 开始计)。

9. **事故复盘报告** —— 写入 `submissions/<SUBMISSION_ID>/02-log-forensics/REPORT.md`(中文或英文均可,建议 300–800 字),至少包含:
   * 根因(机制层面讲清楚:为什么会重复扣款、触发条件是什么、为什么之前/之后的版本没有问题);
   * 关键证据(具体日志行 / 数据,至少 3 条);
   * 时间线(统一用 UTC);
   * 排除了哪些误导线索、依据是什么;
   * 修复与预防建议。

请把你用于分析的脚本放在 `submissions/<SUBMISSION_ID>/02-log-forensics/analysis/` 下(便于评审复核)。

## 评分(满分 100)

| 题目 | 分值 |
|---|---|
| Q1–Q4、Q7 | 各 8 分(精确匹配)|
| Q5 | 10 分(两个币种各 5 分)|
| Q6 | 8 分(user_id 5 分 + 金额 3 分)|
| Q8 | 9 分(每项 3 分;timeout 比例允许 ±0.1)|
| Q9 报告 | 33 分(根因机制 12、证据 8、排除误导 5、时间线 4、建议 4)|
