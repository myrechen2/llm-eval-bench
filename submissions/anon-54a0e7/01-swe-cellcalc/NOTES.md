# Task 01 · cellcalc 修复与功能实现说明

## #1 Columns after Z are broken
- **根因**: `cellcalc/refs.py` 中 `col_to_index` 与 `index_to_col` 将列名当作普通 0-based 26 进制处理（`ord(ch) - ord("A")` 并在最后 `+ 1`，以及 `divmod(idx, 26)` 后 `rem - 1`）。这导致 `'A'` 在高位的值为 0（`'AA'` 与 `'A'` 都映射到 1），且 `idx` 为 26 的倍数时 `rem = 0` 会产生 `'@'` 字符。
- **修改**: 改为标准的双射 26 进制（bijective base-26）：`col_to_index` 中每位累加 `n = n * 26 + (ord(ch) - ord("A") + 1)`；`index_to_col` 中每轮使用 `idx, rem = divmod(idx - 1, 26)` 并取 `chr(ord("A") + rem)`。
- **验证**: 测试 `A..Z`、`AA..AZ`、`BA..ZZ`、`AAA..ZZZ` 的双向转换以及跨 26 列后的单元格读写、公式与区间引用。

## #2 `-2^2` evaluates to 4
- **根因**: `cellcalc/parser.py` 将 `^` 放在 `PRECEDENCE` 表中由 `parse_binary` 处理，而 `parse_binary` 先调用 `parse_unary` 解析左操作数，且循环条件 `PRECEDENCE[...] > min_prec` 使所有二元运算符左结合。因此 `-2^2` 被解析为 `(-2)^2`，`2^3^2` 被解析为 `(2^3)^2`。
- **修改**: 从 `PRECEDENCE` 中移除 `^`，新增 `parse_power()` 层级，置于 `parse_unary()` 之下、`parse_primary()` 之上：左操作数由 `parse_primary()` 解析，遇到 `^` 时右操作数递归调用 `parse_unary()`（既保证 `^` 优先级高于前缀一元运算符，又支持右结合与 `2^-1`、`2^-2^2` 等带符号指数表达式）。
- **验证**: 测试 `=-2^2`（`-4.0`）、`=2^3^2`（`512.0`）、`=2^-1`（`0.5`）、`=2^-2^2`（`0.0625`）及 `=(-2)^2`（`4.0`）。

## #3 Some cells show stale values after an edit
- **根因**: `cellcalc/sheet.py` 的 `_affected_in_order` 仅对依赖图做普通 BFS。当存在长短不一的多条依赖路径（如 `A1 -> B2 -> C5 -> A3` 且 `B2 -> A3`）时，`A3` 在第一层就会被入队并在 `C5` 更新前求值，从而读取到 `C5` 的旧缓存值。
- **修改**: 在 `_affected_in_order` 中，先通过 BFS 收集从 `start` 可达的所有受影响节点，排除处于环上的节点 `cyclic` 后，在非环子图上统计入度并使用 Kahn 拓扑排序生成更新顺序。
- **验证**: 复现 issue 中的菱形/跨层依赖图并在修改 `A1` 后验证 `A3` 立即得到最新值 `41.0`。

## #4 `#CYCLE!` that never goes away
- **根因**: `Sheet.set` 在覆盖或清除已有公式单元格时，只从 `self._formulas` 中移除了该单元格，没有将其从旧依赖项的 `self._dependents[d]` 集合中移除，导致残留了幽灵反向依赖边。
- **修改**: 在 `Sheet.set` 移除旧公式 `old_formula` 时，遍历 `old_formula.deps` 并从 `self._dependents` 中移除当前单元格 `key`。
- **验证**: 测试修改公式解除引用后再反向引用，以及形成真实循环引用（`#CYCLE!`）后通过修改其中一个单元格打破循环，确认所有相关单元格恢复正常计算值。

## #5 `SUM` over a range containing text crashes
- **根因**: `cellcalc/evaluator.py` 的 `_numbers` 在 `from_range` 分支只跳过了 `None`，将区间内的字符串和布尔值原样加入 `nums`（在 Python 中 `bool` 是 `int` 的子类，`True` 被当成 `1` 参与求和，字符串则导致 `TypeError`）。
- **修改**: 在 `_numbers` 的 `from_range` 分支中，当 `v is None or isinstance(v, (str, bool))` 时跳过该单元格；同时保持直接参数走 `to_number(v)` 的强制转换语义。
- **验证**: 测试 `SUM / AVERAGE / MIN / MAX` 在包含文本、布尔值、空单元格的区间上的结果，以及直接传入 `TRUE` 或文本参数时的行为。

## #6 Feature request: `Sheet.copy_cell(src, dst)`
- **设计**:
  1. 若 `src` 为空或字面量，直接调用 `self.set(dst, ...)` 清空或复制字面量。
  2. 若 `src` 为公式，计算列偏移 `dcol = dst.col - src.col` 和行偏移 `drow = dst.row - src.row`。
  3. 使用 `tokenize(text)` 定位公式中的 `REF` 与 `REF : REF` 区间 token（利用每个 token 的精确 `pos` 切片替换），对相对列/行加上偏移并以规范大写格式输出；越界（`col < 1` 或 `row < 1`）的引用或任一端点越界的区间整体替换为 `#REF!`，其余字符（空白、函数名大小写、字符串字面量等）逐字节保留，最后通过 `self.set(dst, "=" + shifted)` 写入并触发重算。
- **验证**: 测试含 `$A$1`、`$A1`、`A$1`、`a1`、区间、越界 `#REF!`、空白与字符串字面量保留、字面量/空单元格复制等场景。
