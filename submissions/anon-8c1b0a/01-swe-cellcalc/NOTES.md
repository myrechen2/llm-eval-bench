# Task 01 · cellcalc 修复与实现说明

## #1 Columns after Z are broken

* **根因**：`cellcalc/refs.py` 中的 `col_to_index` 和 `index_to_col` 使用了普通 26 进制（`'A'` 对应 `0`、最后再 `+ 1`），而非电子表格标准的双射 26 进制（bijective base-26，`A=1 .. Z=26`）。这导致 `'AA'` 被计算为 `0 * 26 + 0 + 1 = 1`（与 `'A'` 冲突），而 `index_to_col(26)` 中 `divmod(26, 26)` 得到 `(1, 0)`，生成了 `'A@'`。
* **修改**：
  * `col_to_index`：每位按 `n = n * 26 + (ord(ch) - ord("A") + 1)` 累加并直接返回 `n`。
  * `index_to_col`：每次循环使用 `idx, rem = divmod(idx - 1, 26)`，对应字符为 `chr(ord("A") + rem)`。
* **验证**：编写了 `Issue1ColumnTests`，验证 `A`、`Z`、`AA`、`AZ`、`BA`、`ZZ`、`AAA`、`ZZZ` 及 `1..2000` 的双向转换，以及跨 `Z` 到 `ZZZ` 列的 `Sheet.set`、`Sheet.get` 和范围聚合公式。

---

## #2 `-2^2` evaluates to 4

* **根因**：`cellcalc/parser.py` 中：
  1. `parse_unary` 对前缀 `+`/`-` 递归调用 `parse_unary`（最终落到 `parse_primary`），导致前缀单目运算符优先级高于所有双目运算符（包括 `^`），使 `-2^2` 被解析为 `(-2)^2`。
  2. `parse_binary` 对所有运算符都递归传入 `PRECEDENCE[op]`，使 `^` 变成了左结合（`2^3^2` 被解析为 `(2^3)^2 = 64`）。
* **修改**：
  * 将 `PRECEDENCE["^"]` 设为 `6`，定义 `UNARY_PRECEDENCE = 5`（与 README 优先级表 1..6 完全一致）。
  * `parse_unary` 解析前缀 `+`/`-` 的操作数时调用 `self.parse_binary(UNARY_PRECEDENCE)`，从而让更高优先级的 `^`（优先级 6）先与操作数结合，而低优先级运算符（`* / + - & =` 等）不在此层结合。
  * 在 `parse_binary` 中对右结合运算符 `^` 递归传入 `PRECEDENCE[op] - 1`（即 `5`），既保证 `2^3^2 = 2^(3^2) = 512`，也支持指数位置的前缀单目运算（如 `2^-1 = 0.5`、`2^-3^2 = 2^-(3^2)`）。
* **验证**：编写了 `Issue2PrecedenceTests`，覆盖 `=-2^2`、`=2^3^2`、`=2^-1`、`=2^-3^2`、`=2^-1*4`、`=4*-2^2` 等组合。

---

## #3 Some cells show stale values after an edit

* **根因**：`cellcalc/sheet.py` 中的 `_affected_in_order` 使用了按单元格坐标排序的 BFS（广度优先遍历），首次访问即入队并标记 `seen`。当依赖图存在多条路径（如菱形/DAG 依赖 `B2 -> C5 -> A3` 且 `B2 -> A3`）且下游节点 `A3` 的坐标字典序小于中间节点 `C5` 时，`A3` 会在 `C5` 更新前被计算，之后不再重算，导致读取到陈旧值。
* **修改**：复用 Tarjan 强连通分量算法（`_tarjan`）。由于 Tarjan 算法按逆拓扑序输出强连通分量（SCC），将弹出的各分量顺序反转后即可得到严格的拓扑更新顺序，保证任意非环节点都在其所有上游依赖更新完成后才求值。
* **验证**：编写了 `Issue3RecalcOrderTests`，测试 issue 中的复现用例以及坐标完全逆序的深层 DAG 依赖更新。

---

## #4 `#CYCLE!` that never goes away

* **根因**：`cellcalc/sheet.py` 的 `Sheet.set` 在覆盖或清除已有公式单元格时，只从 `self._formulas` 中移除了旧公式，却没有把该单元格从旧公式所引用的各个 `d` 的 `self._dependents[d]` 集合中移除。残留的反向依赖边导致后续编辑被误判为环，或真实环被打破后反向依赖图中的环仍然存在。
* **修改**：在 `Sheet.set` 移除旧公式 `old_formula = self._formulas.pop(key, None)` 时，遍历 `old_formula.deps`，将 `key` 从 `self._dependents[d]` 中移除（集合为空时清理键）。
* **验证**：编写了 `Issue4CycleRecoveryTests`，验证覆盖公式后不再产生幽灵环，以及通过字面量、新公式或清空单元格打破双节点环、三节点环和自环后所有相关及下游单元格均恢复正常值。

---

## #5 `SUM` over a range containing text crashes

* **根因**：`cellcalc/evaluator.py` 的 `Evaluator._numbers` 在处理来自范围（`from_range=True`）的值时，只跳过了 `None`（空单元格），将文本（`str`）和布尔值（`bool`，Python 中 `bool` 是 `int` 的子类）直接加入 `nums` 列表，导致 `sum` 遇到字符串抛出 `TypeError`，遇到 `True` 当作 `1` 计入。
* **修改**：在 `Evaluator._numbers` 的 `from_range` 分支中（在 `ErrorValue` 检查之后），仅保留数值类型 `isinstance(v, (int, float)) and not isinstance(v, bool)`，忽略空值、文本和布尔值；直接参数仍保持 `to_number` 强制转换语义。
* **验证**：编写了 `Issue5RangeAggregateTests`，测试包含文本、布尔值和空单元格的范围上的 `SUM / AVERAGE / MIN / MAX`、全非数值范围的边界行为（`SUM=0`、`AVERAGE=#DIV/0!`、`MIN/MAX=0`）以及直接参数与范围混用的情况。

---

## #6 Feature request: `Sheet.copy_cell(src, dst)`

* **实现**：
  * 在 `cellcalc/sheet.py` 中实现 `Sheet.copy_cell(src, dst)`：
    * 若 `src` 为公式，计算偏移 `(dcol, drow) = (dst_col - src_col, dst_row - src_row)`，通过 `tokenize(text, keep_whitespace=True)` 精确扫描 token 流。
    * 遇到范围 `REF [WS] COLON [WS] REF` 时，独立偏移两端点；若任一端点偏移后 `col < 1` 或 `row < 1`，将整个范围替换为单个 `#REF!`，否则将两端点格式化为规范大写形式（保留 `$` 标记及中间空白与冒号）。
    * 遇到单独的 `REF` 时，按相对/绝对标记（`col_abs`、`row_abs`）偏移；越界则替换为 `#REF!`，否则输出规范形式 `format_ref(shifted)`。
    * 其余所有 token（空白、函数名大小写、字符串字面量等）原样拼接保留，最后通过 `self.set(dst, "=" + shifted)` 写入并触发依赖重算。
    * 若 `src` 为字面量则复制该字面量；若 `src` 为空则调用 `self.set(dst, None)` 清空 `dst`。
* **验证**：编写了 `Issue6CopyCellTests`，验证字面量与空单元格复制、相对/混合/绝对引用偏移、格式与字符串字面量原样保留、单引用与范围越界变为 `#REF!` 及重算传播。
