# llm-eval-bench

一个小型、可复现的大模型能力测评仓库,用于比较**不同模型 / 不同思考强度(thinking level)**在 agent 场景下的表现。被测模型在本仓库中读取任务、完成任务、把产出提交到各自的分支;评审方用**不在本仓库中的**隐藏测试和标准答案打分。

> 被测模型请直接阅读 [`AGENTS.md`](AGENTS.md)。下面的内容是给运行测评的人看的。

## 任务一览

任务类型参考了 2025–2026 年各家模型发布时最常报告的几类基准:

| # | 任务 | 对标基准 | 考察能力 | 判分方式 |
|---|---|---|---|---|
| 01 | [修复 cellcalc 的 5 个 bug + 1 个功能](tasks/01-swe-cellcalc/) | SWE-bench Pro / Verified、DeepSWE | 读懂陌生代码库、定位根因、写正确的补丁 | 隐藏单测(85)+ 代码评审(15) |
| 02 | [线上事故日志取证](tasks/02-log-forensics/) | Terminal-Bench 2.x、MRCR/长上下文、DABstep | 30 MB 多源数据检索、时区/口径陷阱、精确统计、根因分析 | 精确答案(67)+ 复盘报告(33) |
| 03 | [竞赛数学 8 题(禁用工具)](tasks/03-math-reasoning/) | AIME / HMMT / HLE(无工具) | 纯推理;通常最能体现思考强度差异 | 精确答案(按难度加权) |
| 04 | [ARC 风格抽象推理 10 题](tasks/04-arc-puzzles/) | ARC-AGI-2 / 3 | 少样本归纳、抽象规则发现 | 网格完全匹配(每题 2 次机会) |
| 05 | [单文件地铁线路规划 Web 应用](tasks/05-frontend-metro/) | WebDev Arena / Design Arena | 前端工程 + 审美 + 带约束的最短路算法 | 隐藏线网自动校验(40)+ Playwright 交互(20)+ 视觉评审(40) |

所有题目都是新写的(数据、题面均为原创或随机生成),降低训练数据污染的影响。

## 运行流程(匿名测评)

评审只看到随机的匿名 ID(形如 `anon-3f9c1a`),看不到模型和思考强度。**"ID ↔ 模型配置"的对应表只保存在你自己手里,不要放进任何仓库**,等评审出分后再公布。

### 1. 每次运行用一个全新的 clone,目录名保持中性

```bash
git clone https://github.com/myrechen2/llm-eval-bench.git bench-run-01
```

目录名不要带模型名(模型可能会把路径写进报告)。全新 clone 也能保证后跑的模型看不到先跑的结果。

### 2. 在 agent 工具里选好模型和思考强度,发送下面的通用提示词(所有模型完全相同)

```text
请完整阅读当前仓库根目录的 AGENTS.md,并严格按照其中的规则,独立完成全部任务并提交。
过程中不要向我提问;遇到不确定的地方,自行做出合理判断,并在相应的 NOTES.md / REPORT.md 中写明。
```

模型会运行 `scripts/new_submission_id.py` 领取匿名 ID,在 `submit/<ID>` 分支上完成并推送,最后在回复里报出 ID。

### 3. 私下记录对应关系和用量

在你自己的表格里记一行:匿名 ID、模型、思考强度、所用工具、token 用量、费用、耗时、是否干预过。评审出分后再把这张表给评审,用来做"分数 / 成本 / 耗时"的综合对比。

### 4. 全部跑完后通知评审

不要把 `submit/*` 分支合并到 main,告诉评审"都跑完了"即可。

## 公平性建议

* 同一批对比尽量用**同一个 agent 工具**,只改模型和思考强度。
* 如果上下文不够,可以分多次会话:在**同一个 clone 目录**里开新会话,提示词改成"……只完成任务 0X",模型会沿用同一个匿名 ID。
* 预算允许的话,同一配置跑 2–3 次(每次新 clone、新 ID),减小偶然性。

## 仓库结构

```
AGENTS.md / GEMINI.md / CLAUDE.md   被测模型的规则(后两者指向 AGENTS.md)
tasks/0X-*/                         任务说明与数据(只读)
submissions/_template/meta.json     自评模板
submissions/<SUBMISSION_ID>/        各模型的提交(只存在于各自的 submit/* 分支)
scripts/new_submission_id.py        生成匿名 ID、创建提交分支
scripts/check_submission.py         提交格式与匿名性自检(不包含答案)
```
