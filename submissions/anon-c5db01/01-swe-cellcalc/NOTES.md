# Task 01 · cellcalc 修复与实现说明

## Issue #1: 多字母列名（`Z` 之后）损坏
- **根因**：`cellcalc/refs.py` 中 `col_to_index` 按 0-based 数字累加后末尾加 1（导致 `AA` 被算成 `0*26 + 0 + 1 = 1`，覆盖 `A`）；`index_to_col` 使用 `divmod(idx, 26)` 而非 bijective base-26 的 `divmod(idx - 1, 26)`（导致 `26` 算出 `'A@'`）。
- **修改**：将 `col_to_index` 改为每步按 `ord(ch) - ord("A") + 1` 做 26 进制累加，并限制为 ASCII 字母；将 `index_to_col` 改为 `divmod(idx - 1, 26)` 与 `ord("A") + rem`。定义 `MAX_COL` 为 3 字母上限（`ZZZ` = 18278）。
- **验证**：新增 `Issue1MultiLetterColumnsTests`，覆盖 `A/Z/AA/AZ/BA/ZZ/AAA/ZZZ` 双向转换及 `Sheet` 中读写、公式与范围引用。

## Issue #2: `-2^2` 求值错误及 `^` 结合性错误
- **根因**：`cellcalc/parser.py` 中 `PRECEDENCE["^"] = 5` 与一元操作符优先级混淆，且 `parse_unary` 递归调用 `parse_unary()`（高于所有二元运算），导致 `-2^2` 被解析为 `(-2)^2`；同时 `parse_binary` 对所有运算符传入 `PRECEDENCE[op]`，使 `^` 变成左结合。
- **修改**：将 `PRECEDENCE["^"]` 设为 `6`，定义 `UNARY_PRECEDENCE = 5` 和 `RIGHT_ASSOC = {"^"}`；`parse_unary` 改为调用 `self.parse_binary(UNARY_PRECEDENCE)`，`parse_binary` 对右结合运算符传入 `prec - 1`。（同时将 `parse_ref` 的 `ValueError` 包装为 `FormulaSyntaxError`，保证如 `=A0` 抛语法错误。）
- **验证**：新增 `Issue2PrecedenceTests`，验证 `=-2^2` (-4)、`=(-2)^2` (4)、`=2^3^2` (512)、`=2^-1` (0.5)、`=-2^3^2` (-512)、`=3*-2^2` (-12)、`=2^-1^2` (0.5) 等。

## Issue #3: 编辑后部分单元格出现陈旧值
- **根因**：`cellcalc/sheet.py` 中 `_affected_in_order` 使用 BFS 遍历 `_dependents`，而非拓扑序。在菱形/多层依赖图中（如 `A1 -> B2 -> C5 -> A3` 且 `B2 -> A3`），若下游节点距离起点跳数更少，会先于其上游依赖被求值。
- **修改**：在 `_recalculate` 中先将 `cyclic` 集合中的公式单元格赋值为 `#CYCLE!`，再由 `_affected_in_order` 对可达子图排除 `cyclic` 后的 DAG 执行 Kahn 拓扑排序并逐一求值。
- **验证**：新增 `Issue3TopologicalRecalcTests`，验证菱形依赖、跨位置多层 DAG 及环与 DAG 混合图的求值结果。

## Issue #4: `#CYCLE!` 无法清除
- **根因**：`Sheet.set` 覆盖或清空旧公式时，只从 `self._formulas` 移除该单元格，未从 `self._dependents[d]` 中移除旧依赖边，导致残留幽灵边在后续形成假环或阻断环解除。
- **修改**：在 `Sheet.set` 中弹出 `old_formula` 后，遍历 `old_formula.deps` 从 `self._dependents[d]` 中 `discard(key)`（空集合同步清理）。
- **验证**：新增 `Issue4CycleCleanupTests`，验证公式改写为字面量、真实循环被打破/清空，以及语法错误保持原依赖图不受破坏。

## Issue #5: `SUM` 等聚合函数对含文本/布尔值的范围处理错误
- **根因**：`cellcalc/evaluator.py` 中 `_numbers` 对 `from_range=True` 的成员仅跳过了 `None`，将文本和布尔值直接加入 `nums`，导致文本触发 `TypeError`，布尔值按 `0/1` 参与计算。
- **修改**：在 `_numbers` 的 `from_range` 分支中，仅保留非布尔值的数值（`isinstance(v, (int, float)) and not isinstance(v, bool)`），跳过空值、文本和布尔值；直接参数与错误传播逻辑保持不变。
- **验证**：新增 `Issue5AggregateRangeTests`，验证 `SUM/AVERAGE/MIN/MAX` 在包含文本、布尔、空值、全非数值及错误值时的行为。

## Issue #6: 实现 `Sheet.copy_cell(src, dst)`
- **修改**：在 `cellcalc/sheet.py` 实现 `Sheet.copy_cell` 与辅助函数 `_shift_ref`、`_shift_formula`：
  - 若 `src` 为空或字面量，直接调用 `self.set(dst, self._literals.get(src_key))`；
  - 若 `src` 为公式，使用 `tokenize(text, keep_whitespace=True)` 逐 token 重写：仅对 `REF` token（及 `REF [WS...] : [WS...] REF` 范围）按 `(dst.col - src.col, dst.row - src.row)` 平移未加 `$` 锁定的分量，规范化为大写并保留 `$`；若单一引用或范围任一端点移至 `< A`、`row < 1` 或超过 3 字母列上限（`> ZZZ`），将其（或整个 `X:Y`）替换为 `#REF!`；其余空白、函数名大小写、字符串字面量等逐字节保留，并通过 `self.set` 触发完整重算。
- **验证**：新增 `Issue6CopyCellTests`，验证字面量/空值复制、混合 `$` 锚点与小写引用规范化、字符串/空格/大小写保留、越界替换 `#REF!` 及下游联动重算。

## 测试结果
在 `submissions/anon-c5db01/01-swe-cellcalc/project` 下运行：
`py -m unittest discover -s tests -t . -v`
原有 14 个测试 + 新增 16 个测试，共 30 个测试全部通过（OK）。
