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

## 运行流程

### 1. 给每个被测配置起一个 SUBMISSION_ID

格式建议:`<模型>__<思考强度>__<工具>`,全小写,只用 `a-z 0-9 . _ -`。例如:

```
gemini-3.1-pro__high__gemini-cli
gemini-3.1-pro__low__gemini-cli
gemini-3-flash__medium__gemini-cli
```

### 2. 每个配置用一个**全新的 clone**(重要)

避免后跑的模型看到先跑的模型的分支或残留文件:

```bash
git clone https://github.com/myrechen2/llm-eval-bench.git run-<SUBMISSION_ID>
cd run-<SUBMISSION_ID>
```

### 3. 在 agent 工具里设置好模型和思考强度,然后发送提示词

```text
你正在参加一个模型能力测评。请先完整阅读仓库根目录的 AGENTS.md,并严格遵守其中的规则。
你的 SUBMISSION_ID 是:<在这里填写>
请依次完成 tasks/ 下的全部 5 个任务,按 AGENTS.md 的要求提交到分支 submit/<SUBMISSION_ID> 并推送。
过程中不要向我提问;遇到不确定的地方自行做出合理判断,并在对应的 NOTES / REPORT 中写明。
```

如果上下文不够用或想分开统计,也可以每个任务开一个新会话,把第三行改成“请只完成任务 0X”。

### 4. 跑完后记录用量

把工具里能看到的 token 用量、费用、耗时补到 `submissions/<SUBMISSION_ID>/meta.json` 的 `usage` 中(或者直接告诉评审)。比较思考强度时,**分数 / 成本 / 耗时**要一起看。

### 5. 全部跑完后通知评审

不要把 `submit/*` 分支合并到 main。告诉评审有哪些分支即可。

## 公平性建议

* 同一批对比尽量用**同一个 agent 工具**(例如都用 Gemini CLI),只改模型和思考强度;工具不同会显著影响结果。
* 思考强度:Gemini 3 系列 API 的参数是 `thinking_level`(不同型号支持的档位不同,如 `low` / `medium` / `high`);旧的 2.5 系列用 `thinking_budget`。请在 `meta.json` 的 `thinking_level` 里如实记录你实际设置的值。
* 跑的过程中尽量不要干预;如果干预了,把次数记到 `meta.json` 的 `human_interventions`。
* 预算允许的话,同一配置跑 2–3 次取平均,单次结果的方差可能不小。

## 仓库结构

```
AGENTS.md / GEMINI.md / CLAUDE.md   被测模型的规则(后两者指向 AGENTS.md)
tasks/0X-*/                         任务说明与数据(只读)
submissions/_template/meta.json     元数据模板
submissions/<SUBMISSION_ID>/        各模型的提交(只存在于各自的 submit/* 分支)
scripts/check_submission.py         提交格式自检(不包含答案)
```
