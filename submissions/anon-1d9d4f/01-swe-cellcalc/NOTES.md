# Task 01 · cellcalc 修复与功能实现说明

## Issue #1: Columns after Z are broken

* **根因**：`cellcalc/refs.py` 中 `col_to_index` 使用 0-based 位权 `(ord(ch) - ord("A"))` 并在最后 `+ 1`，导致 `'AA'` 被算作 `0*26 + 0 + 1 = 1`（与 `'A'` 冲突）；`index_to_col` 使用 `divmod(idx, 26)` 而非双射 26 进制的 `divmod(idx - 1, 26)`，导致 `26` 余数为 `0` 映射为 `'A@'`。
* **修改**：将 `col_to_index` 改为双射 26 进制累加 `n = n * 26 + (ord(ch) - ord("A") + 1)`（同时校验 `isascii()`），将 `index_to_col` 改为 `idx, rem = divmod(idx - 1, 26)` 与 `chr(ord("A") + rem)`。
* **验证**：测试 `A..ZZZ` 边界值、`1..2000` 及 `18270..18278` 双向往返转换，以及在 `Sheet` 中读写和汇总跨 Z 列单元格。

## Issue #2: `-2^2` evaluates to 4

* **根因**：`cellcalc/parser.py` 将 `^` 放在 `PRECEDENCE` 表的二元运算符循环中，且 `parse_binary` 以左结合方式调用 `parse_unary()` 作为左操作数，因此 `-2^2` 被解析为 `(-2)^2`，`2^3^2` 被解析为 `(2^3)^2`。
* **修改**：将 `^` 从 `PRECEDENCE` 中移除，在 `parse_unary` 之下新增 `parse_power`：`base = parse_primary()`，若后接 `^` 则递归调用 `parse_unary()` 作为右操作数。由此实现 `^` 优先级高于一元 `+/-`、右结合，且支持 `2^-1`、`2^-3^2` 等带符号指数。
* **验证**：测试 `-2^2 = -4`、`(-2)^2 = 4`、`2^3^2 = 512`、`2^-1 = 0.5`、`-2^-2 = -0.25`、`2^-3^2`、`2*3^2 = 18` 等表达式。

## Issue #3: Some cells show stale values after an edit

* **根因**：`Sheet._affected_in_order` 使用 BFS 遍历 `_dependents`，当依赖图存在多条不等长路径（菱形依赖）或不同列/行顺序时，下游单元格可能在所有上游单元格更新前被求值，读取到旧值。
* **修改**：在 `cellcalc/sheet.py` 中用 `_reachable` + `_topo_order`（Kahn 拓扑排序）替代 BFS：先将 Tarjan SCC 识别出的环成员统一置为 `#CYCLE!`，再对可达的非环子图按依赖拓扑序依次求值。
* **验证**：复现 issue 中的菱形依赖及更深的多路径 DAG，验证每次 `set` 后所有下游值均准确更新。

## Issue #4: `#CYCLE!` that never goes away

* **根因**：`Sheet.set` 覆写或清空公式单元格时，仅从 `self._formulas` 移除旧公式，未从 `self._dependents` 中删除旧依赖边，导致残留边形成幽灵环或冗余依赖。
* **修改**：在 `Sheet.set` 中弹出 `old_formula` 后，遍历 `old_formula.deps` 从 `self._dependents[d]` 移除当前单元格键（集合为空时顺带清理键）。
* **验证**：测试公式改字面量后再反向引用、打破双单元格环、通过清空单元格打破环等场景，确认 `#CYCLE!` 正确消除且下游恢复正常值。

## Issue #5: `SUM` over a range containing text crashes

* **根因**：`Evaluator._numbers` 处理区域成员（`from_range=True`）时只跳过 `None`，直接把文本和布尔值加入数值列表，导致文本触发 `TypeError`，布尔值 `True` 被当作 `1` 参与计算。
* **修改**：在 `cellcalc/evaluator.py` 的 `_numbers` 中，对区域成员仅收集 `isinstance(v, (int, float)) and not isinstance(v, bool)` 的数值（错误值仍优先传播），忽略空值、文本和布尔值；直接参数保持原有 `to_number` 强制转换规则。
* **验证**：测试 `SUM / AVERAGE / MIN / MAX` 在包含数字、文本、布尔值、空单元格及错误值的区域和混合直接参数上的行为。

## Issue #6: Feature request: `Sheet.copy_cell(src, dst)`

* **设计与实现**：
  * 若 `src` 为空或字面量，直接通过 `self.set(dst, None / literal)` 写入并触发重算。
  * 若 `src` 为公式，利用 `tokenize(text, keep_whitespace=True)` 保留除单元格引用外的全部 token 字节（空格、函数名大小写、字符串字面量等）。
  * 对每个 `REF`（以及允许中间带空白的 `REF : REF` 区域），按 `(dst.col - src.col, dst.row - src.row)` 偏移未加 `$` 的分量，并以规范大写形式输出；若偏移后超出合法范围（列 `< 1`、行 `< 1` 或列超过 3 字母上限 `ZZZ`），单引用替换为 `#REF!`，区域整体替换为单个 `#REF!`。
  * 最后调用 `self.set(dst, "=" + rewritten)`，使 `dst` 正常登记依赖并参与重算。
* **验证**：测试字面量/空单元格复制、相对/绝对/混合引用偏移、格式与字符串字面量逐字节保留、单引用与区域越界变为 `#REF!` 以及复制后下游单元格自动重算。

## 测试结果

使用 Python 3.11 运行 `py -m unittest discover -s tests -t . -v`，原有 14 个测试与新增 17 个测试（`tests/test_issues.py`）共 31 个测试全部通过。
