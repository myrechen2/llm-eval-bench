# 任务 01 · 真实仓库修 Bug + 实现功能(SWE 类)

**对标:** SWE-bench Pro / SWE-bench Verified / DeepSWE —— 在一个陌生代码库中理解代码、定位并修复 issue、补全功能,最终由**隐藏测试**判分。

## 你要做什么

`project/` 是一个小型电子表格公式引擎 `cellcalc`(纯 Python,无第三方依赖)。`ISSUES.md` 中有 6 个待处理的 issue(5 个 bug + 1 个功能需求)。

1. 先把整个 `project/` 目录复制到你的提交目录:
   ```bash
   mkdir -p submissions/<SUBMISSION_ID>/01-swe-cellcalc
   cp -r tasks/01-swe-cellcalc/project submissions/<SUBMISSION_ID>/01-swe-cellcalc/
   ```
   之后**只修改你自己目录下的副本**,不要改动 `tasks/` 下的任何文件。
2. 解决 `ISSUES.md` 中的全部 6 个 issue。
3. 现有测试必须继续通过:
   ```bash
   cd submissions/<SUBMISSION_ID>/01-swe-cellcalc/project
   python -m unittest discover -s tests -t .
   ```
   欢迎在 `tests/` 里新增你自己的测试。
4. 在 `submissions/<SUBMISSION_ID>/01-swe-cellcalc/NOTES.md` 中简要写明:每个 issue 的根因、你的修改、你如何验证。

## 约束

* 只能使用 Python 标准库;不要修改公开 API 的名字和签名(`Sheet.set / get / get_formula / get_content / copy_cell`、`cellcalc.refs.*`)。
* 行为规范以 `project/README.md` 和 `ISSUES.md` 为准。
* 不要删除或弱化已有测试。

## 评分(满分 100)

| 部分 | 分值 | 说明 |
|---|---|---|
| 隐藏测试 | 85 | 每个 issue 一组隐藏测试(每组权重相同)+ 回归测试组 |
| 代码质量 | 15 | 评审者阅读你的 diff:修复是否针对根因、是否简洁、是否引入新问题、NOTES.md 是否清楚 |

公开测试不通过的提交,隐藏测试部分最多得 50%。
