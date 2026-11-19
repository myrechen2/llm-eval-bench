# 被测模型必读(AGENTS.md)

你正在参加一个**大模型能力测评**。本文件是唯一权威的规则说明,开始任何工作前请完整阅读。

## 0. 你的身份

运行你的人会在提示词中告诉你一个 **SUBMISSION_ID**(例如 `gemini-3.1-pro__high__gemini-cli`)。
下文所有 `<SUBMISSION_ID>` 都替换成它。如果提示词里没有给出,**停下来询问**,不要自己编一个。

## 1. 任务列表

| # | 目录 | 类型 | 建议时长 |
|---|---|---|---|
| 01 | `tasks/01-swe-cellcalc/` | 在陌生代码库中修复 5 个 bug + 实现 1 个功能(隐藏测试判分) | 30–60 min |
| 02 | `tasks/02-log-forensics/` | 30 MB 多源日志 / CSV 的事故取证、精确统计 + 复盘报告 | 30–60 min |
| 03 | `tasks/03-math-reasoning/` | 8 道竞赛数学题,**禁止使用任何工具** | 20–60 min |
| 04 | `tasks/04-arc-puzzles/` | 10 道 ARC 风格抽象推理题 | 20–40 min |
| 05 | `tasks/05-frontend-metro/` | 单文件 Web 应用:地铁线路图 + 路径规划 | 40–90 min |

每个任务目录下的 `README.md` 是该任务的详细说明和评分标准。除非提示词另有指定,请**按顺序完成全部任务**。

## 2. 提交方式

1. 在**新分支**上工作:
   ```bash
   git checkout -b submit/<SUBMISSION_ID>
   ```
2. 所有产出只能写在 `submissions/<SUBMISSION_ID>/` 下,结构如下(以各任务 README 为准):
   ```
   submissions/<SUBMISSION_ID>/
   ├── meta.json                    # 从 submissions/_template/meta.json 复制并填写
   ├── 01-swe-cellcalc/   project/ (复制后修改的代码) + NOTES.md
   ├── 02-log-forensics/  answers.json + REPORT.md + analysis/
   ├── 03-math-reasoning/ answers.json + solutions.md
   ├── 04-arc-puzzles/    answers.json + NOTES.md(可选)
   └── 05-frontend-metro/ index.html + NOTES.md
   ```
3. **不要修改** `tasks/`、`scripts/`、根目录文件或其它任何人的目录。
4. 提交前运行格式自检(只检查格式,不会告诉你对错):
   ```bash
   python scripts/check_submission.py <SUBMISSION_ID>
   ```
5. 每完成一个任务就 commit 一次(便于评审看过程),全部完成后推送:
   ```bash
   git add submissions/<SUBMISSION_ID>
   git commit -m "<SUBMISSION_ID>: task 0X"
   git push -u origin submit/<SUBMISSION_ID>
   ```
   **不要合并到 main,不要开 PR**(除非运行你的人要求)。如果推送失败(没有权限/网络),在最终回复中说明,产出保留在本地即可。

## 3. 公平性规则(违反会导致该任务作废)

* **不要查看其它提交**:不要 `git fetch`/`checkout`/`log` 其它 `submit/*` 分支,不要读取 `submissions/` 下除自己和 `_template` 以外的目录。
* **不要上网搜索答案**。所有任务都可以离线完成,也不需要安装任何第三方依赖(Python 标准库 + 浏览器即可)。
* 任务 03 禁止运行代码/计算器(详见其 README),其它任务可以自由写脚本、跑测试。
* 不要试图寻找"标准答案"或隐藏测试——它们不在这个仓库里。
* 全程**不要向运行你的人提问**(SUBMISSION_ID 缺失除外);遇到歧义自行做出合理判断,并在对应的 NOTES/REPORT 里写明你的假设。
* 不要中途放弃:时间不够时优先保证每个任务都有可评分的提交(哪怕不完整),并在 NOTES 中说明。

## 4. meta.json

从 `submissions/_template/meta.json` 复制后填写你**确定知道**的字段,不知道的保留 `null`(运行你的人会补全 token 用量等信息)。在 `self_assessment` 中给每个任务一句话自评,包括你认为最可能出错的地方。

## 5. 最终回复

全部完成后,在对话中给出一个简短总结:每个任务的完成情况、你最不确定的地方、是否成功推送。
