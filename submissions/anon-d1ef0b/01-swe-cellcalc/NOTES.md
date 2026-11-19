# Task 01 · cellcalc 修复与实现说明

## Issue #1: Columns after Z are broken

* **根因**: `cellcalc/refs.py` 中的 `col_to_index` 和 `index_to_col` 未按双射 26 进制(bijective base-26)实现:
  * `col_to_index` 将字母映射为 `0..25` 并在最后 `+ 1`,导致 `AA` 算出 `0*26 + 0 + 1 = 1`(与 `A` 冲突)。
  * `index_to_col` 对 `idx` 直接做 `divmod(idx, 26)` 且使用 `rem - 1`,导致 `26` 的余数为 `0`,产出 `'A@'` 而非 `'Z'`。
* **修改**:
  * `col_to_index` 改为每位移位后累加 `(ord(ch) - ord("A") + 1)`,并校验 ASCII 字母。
  * `index_to_col` 改为每次 `idx, rem = divmod(idx - 1, 26)` 并映射 `chr(ord("A") + rem)`。
  * 增加常量 `MAX_COL_INDEX = col_to_index("ZZZ")`(18278)供边界校验使用。
* **验证**: 在 `tests/test_issues.py` 中对 `1..18278`(`A..ZZZ`)全量做 `index_to_col` / `col_to_index` 互逆检验,并测试宽列表格读写、公式及跨 `Z`/`AA`/`ZZ`/`AAA`/`ZZZ` 范围计算。

## Issue #2: `-2^2` evaluates to 4

* **根因**: `cellcalc/parser.py` 中:
  1. `parse_unary` 递归调用 `parse_unary()` 而非按优先级继续解析,使一元 `-`/`+` 绑定得比所有二元运算符(包括 `^`)都紧,导致 `-2^2` 被解析为 `(-2)^2`。
  2. `PRECEDENCE["^"]` 为 5 且 `parse_binary` 统一使用 `PRECEDENCE[op]` 作为 `min_prec`,使 `^` 呈左结合,导致 `2^3^2` 被解析为 `(2^3)^2 = 64`。
* **修改**:
  * 将 `PRECEDENCE["^"]` 提升为 6,设 `UNARY_PRECEDENCE = 5` 与 `RIGHT_ASSOC = {"^"}`。
  * `parse_binary` 对右结合运算符传入 `prec - 1`,使 `^` 右结合。
  * `parse_unary` 对一元 `+`/`-` 调用 `self.parse_binary(UNARY_PRECEDENCE)`,使 `-2^2` 解析为 `-(2^2) = -4`,同时 `2^-1` 解析为 `2^(-1) = 0.5`、`2^-3^2` 解析为 `2^(-(3^2))`,严格符合 README 优先级表。
  * 顺带将 `parse_primary` 中 `parse_ref` 抛出的 `ValueError`(如 `=A0`)转为 `FormulaSyntaxError`。
* **验证**: 在 `tests/test_issues.py` 覆盖 `-2^2`、`--2^2`、`(-2)^2`、`2^3^2`、`2^-1`、`2^-3^2`、`3*-2^2`、`10-2^3` 等组合。

## Issue #3: Some cells show stale values after an edit

* **根因**: `cellcalc/sheet.py` 的 `_affected_in_order` 使用 BFS 遍历 `_dependents`。在菱形或多路径依赖图中(如 `A1 -> B2 -> C5 -> A3` 且 `B2 -> A3`),若依赖更深的节点坐标排序靠前,BFS 会先求值 `A3` 再求值 `C5`,导致 `A3` 读到旧值。
* **修改**: 将 `_cycle_members` 与 `_affected_in_order` 合并为 `_sccs_in_order(start)`:使用迭代式 Tarjan 强连通分量算法遍历所有可达依赖者;Tarjan 产出的 SCC 序列本身即为依赖图的逆拓扑序,反转后即得冷凝 DAG 的合法拓扑序。`_recalculate` 按该顺序依次处理每个 SCC:大小 > 1 或含自环的 SCC 内公式置 `#CYCLE!`,其余单节点公式按拓扑序求值,保证所有上游(包括新产生的 `#CYCLE!`)在下游之前更新。
* **验证**: 复现 issue 中的菱形用例,并新增深层多路径 DAG 与带环及下游传播的更新测试。

## Issue #4: `#CYCLE!` that never goes away

* **根因**: `Sheet.set` 覆盖或清空已有公式单元格时,只从 `self._formulas` 删除了该单元格,未从 `self._dependents[d]` 中移除其旧依赖边。导致旧依赖残留,后续建立反向引用时会误判为环,且真实环被打破后也无法恢复。
* **修改**:
  * 在 `Sheet.set` 中先完成新公式解析或字面量校验(确保异常时不破坏原表状态),再取出 `old_formula = self._formulas.pop(key, None)` 并将其从所有 `self._dependents[d]` 中移除(同时清理空集合)。
  * 配合 `_sccs_in_order` 的拓扑重算,破环后所有曾经在环内及下游的单元格均会重新求值并恢复正常值。
* **验证**: 测试 issue 复现用例、两单元格/三单元格环被字面量或清空打破、自环打破、公式改写目标依赖以及语法错误不破坏旧依赖。

## Issue #5: `SUM` over a range containing text crashes

* **根因**: `cellcalc/evaluator.py` 的 `_numbers` 在处理来自范围(`from_range=True`)的值时只跳过了 `None`,直接把字符串和布尔值加入 `nums`,导致字符串触发 `TypeError`,布尔值被当作 `1`/`0` 计入。
* **修改**: 对 `from_range=True` 的非错误值,改为 `if isinstance(v, bool) or not isinstance(v, (int, float)): continue`,忽略空值、文本和布尔值;直接参数仍走 `to_number` 强转;错误值优先向上传播。
* **验证**: 测试 `SUM`/`AVERAGE`/`MIN`/`MAX` 在含文本/布尔/空单元格范围、全非数值范围、混合直接参数与范围、以及含错误值范围下的行为。

## Issue #6: Feature request `Sheet.copy_cell(src, dst)`

* **设计假设与实现**:
  * 利用 `tokenizer.tokenize(text, keep_whitespace=True)` 保留公式中所有非引用 token 的原始文本(空格、函数名大小写、含引用样式的字符串字面量及转义引号等)。
  * 仅对 `REF` token(以及 `REF [WS*] COLON [WS*] REF` 组成的范围)执行相对坐标偏移 `(dst.col - src.col, dst.row - src.row)`,带 `$` 的行或列保持不变;偏移后的有效引用通过 `format_ref` 输出规范的大写形式。
  * 若偏移后列 `< 1`、行 `< 1` 或列超出 3 字母上限 `ZZZ`(无法表示为合法列引用),单引用替换为 `#REF!`,范围整体(含冒号与空白)替换为单个 `#REF!`。
  * 对字面量与空单元格分别通过 `self.set(dst, literal)` 和 `self.set(dst, None)` 写入,确保目标单元格及下游完全参与依赖登记与重算。
* **验证**: 测试字面量/空单元格复制、绝对/相对/混合引用、带空格范围、越界单引用与越界范围、跨 `Z`/`ZZ` 及越过 `ZZZ`、格式化与字符串字面量逐字节保留、下游重算联动以及复制到自身。
