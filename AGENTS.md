# 被测模型必读(AGENTS.md)

你正在参加一个**大模型能力测评**。本文件是唯一权威的规则说明,开始任何工作前请完整阅读。

## 0. 你的身份(匿名)

这是一次**匿名测评**:评审只根据产出的效果打分,看不到也不应该看到是哪个模型提交的。

开始前在仓库根目录运行:

```bash
python scripts/new_submission_id.py
```

它会生成一个随机的匿名 **SUBMISSION_ID**(形如 `anon-3f9c1a`),创建分支 `submit/<SUBMISSION_ID>`,为本仓库设置匿名的 git 身份,并创建 `submissions/<SUBMISSION_ID>/meta.json`。输出的最后一行就是你的 ID。下文所有 `<SUBMISSION_ID>` 都替换成它。

* 如果你已经在某个 `submit/...` 分支上(同一次测评分多次会话完成),脚本会沿用这个分支的 ID,**不要另建新 ID**。
* 不要手动改 ID,不要自己编一个。

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

1. 运行 `python scripts/new_submission_id.py`(见第 0 节),它会帮你切到分支 `submit/<SUBMISSION_ID>`。
2. 所有产出只能写在 `submissions/<SUBMISSION_ID>/` 下,结构如下(以各任务 README 为准):
   ```
   submissions/<SUBMISSION_ID>/
   ├── meta.json                    # 脚本已创建,完成后填写 self_assessment
   ├── 01-swe-cellcalc/   project/ (复制后修改的代码) + NOTES.md
   ├── 02-log-forensics/  answers.json + REPORT.md + analysis/
   ├── 03-math-reasoning/ answers.json + solutions.md
   ├── 04-arc-puzzles/    answers.json + NOTES.md(可选)
   └── 05-frontend-metro/ index.html + NOTES.md
   ```
3. **不要修改** `tasks/`、`scripts/`、根目录文件或其它任何人的目录。
4. 每完成一个任务就 commit 一次。提交信息只写 `<SUBMISSION_ID>: task 0X` 这种格式,**不要**添加任何签名、
   `Co-Authored-By`、"Generated with ..." 之类的尾注,也不要改动脚本设置的 git 作者身份:
   ```bash
   git add submissions/<SUBMISSION_ID>
   git commit -m "<SUBMISSION_ID>: task 0X"
   ```
5. 全部完成后运行格式与匿名性自检(不会告诉你答案对错),有 FAIL 就按提示修复后再跑一遍:
   ```bash
   python scripts/check_submission.py <SUBMISSION_ID>
   ```
6. 推送:
   ```bash
   git push -u origin submit/<SUBMISSION_ID>
   ```
   **不要合并到 main,不要开 PR**。如果推送失败(没有权限/网络),在最终回复中说明,产出保留在本地即可。

## 3. 匿名规则(违反会导致该提交作废)

在提交目录的**任何文件**(代码、注释、NOTES、REPORT、meta.json)、**提交信息和 git 作者信息**中,都不得出现:

* 你的模型名称、版本、厂商、所用的 agent 工具或产品名;
* 推理/思考强度、思考预算等配置信息;
* 任何能让评审推断出你是谁的自我介绍(例如"作为 XX 开发的模型……")。

写作时直接陈述内容即可,用"我"或不用人称都可以。

## 4. 公平性规则(违反会导致该任务作废)

* **不要查看其它提交**:不要 `git fetch`/`checkout`/`log` 其它 `submit/*` 分支,不要读取 `submissions/` 下除自己和 `_template` 以外的目录。
* **不要上网搜索答案**。所有任务都可以离线完成,也不需要安装任何第三方依赖(Python 标准库 + 浏览器即可)。
* 任务 03 禁止运行代码/计算器(详见其 README),其它任务可以自由写脚本、跑测试。
* 不要试图寻找"标准答案"或隐藏测试——它们不在这个仓库里。
* 全程**不要向运行你的人提问**;遇到歧义自行做出合理判断,并在对应的 NOTES/REPORT 里写明你的假设。
* 不要中途放弃:时间不够时优先保证每个任务都有可评分的提交(哪怕不完整),并在 NOTES 中说明。

## 5. meta.json

只填写 `self_assessment`(每个任务一句话自评,包括你认为最可能出错的地方)和可选的 `notes`。不要添加其它字段。

## 6. 最终回复

全部完成后,在对话中给出一个简短总结:**你的 SUBMISSION_ID**、每个任务的完成情况、你最不确定的地方、是否成功推送。
