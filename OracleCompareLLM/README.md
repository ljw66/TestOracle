# C 测试断言语义等价性判断（方案1 + 方案2）

## 文件说明

- `assertion_normalizer.py` — **方案1**：从C源码中提取断言宏调用，归一化为统一的
  `(op, lhs, rhs)` 三元组，并做交换律等结构层面的等价判断。已在沙箱内跑通自测（含一个
  真实踩过的坑，见下方"已知问题"）。
- `semantic_equivalence.py` — **方案2**：把归一化后的操作数表达式转成 Z3 符号表达式，
  用 SMT 求解判断两个断言是否逻辑等价（`assert Xor(e1, e2)` 不可满足 ⇒ 等价）。
  **注意：这部分我在当前沙箱环境里没有 `z3-solver` 也没有网络，无法实际跑通验证求解结果的正确性**，
  只做了语法编译检查 + 用一个假的 z3 桩模块跑通了调用链路（确认不会有 Python 级别的 AttributeError/
  TypeError），SMT 逻辑本身的正确性请你在本地装好 `z3-solver` 后按下面的方法自测。
- `main.py` — **主函数**：递归遍历 `root_dir` 下所有子文件夹里的 json 文件，读取每条用例的
  `reference_oracle` / `generated_oracle`（支持一个字段里包含多条断言、支持 ```` ```c ``` ```` 代码块包裹），
  用最大二分匹配（而不是简单按顺序配对）判断两组断言的对应关系，输出详细结果 + 汇总统计
  （precision / recall / f1 / 完全匹配率）。已在沙箱内用模拟目录结构+边界情况（空预言、JSON格式错误）
  跑通全流程。

## 安装

```bash
pip install pycparser z3-solver
```

## 本地自测方法（务必先跑一遍）

```bash
cd oracle_equiv
python3 assertion_normalizer.py     # 应输出5条断言两两等价性全部为True
python3 semantic_equivalence.py     # 内置9组测试用例，会打印 预期 vs 实际 是否一致（✓/✗）
python3 pipeline.py                 # 端到端示例
```

`semantic_equivalence.py` 里的 `__main__` 部分内置了9组精心设计的用例（包括交换律、
双重否定、strcmp建模、明显不等价的反例等），运行后会逐行打印 `✓`/`✗`，如果出现 `✗`，
说明某个分支的转换逻辑有问题，麻烦把完整输出发给我，我们一起排查（我这边没环境实测过这部分，
不排除有边界条件没考虑到）。

## 批量处理 json 数据集

假设目录结构：
```
dataset/
    module_a/
        case1.json
        case2.json
    module_b/
        case3.json
```

每个 json 文件内容是一个列表，每个元素包含 `function_name`、`test_name`、`prefix`、
`reference_oracle`、`generated_oracle` 字段（`generated_oracle` 可以被 ` ```c ... ``` ` 包裹，
两个字段都可能包含不止一条断言）。

运行：
```bash
python3 Compare.py dataset --output results.json --verbose
```

会做两件事：
1. 把每条用例的详细比较结果（匹配上的断言对、遗漏的、多余的、precision/recall/f1）写入
   `results.json`
2. 在控制台打印整体汇总统计（平均precision/recall/f1、完全匹配率、需要人工复核的用例数等）

**关于 precision / recall 的定义**：由于生成的断言数量和参考断言数量往往不一致（比如LLM只生成了
部分断言，或断言顺序不同），`main.py` 内部用最大二分匹配（Kuhn算法）而不是按顺序逐一配对：
- `precision` = 生成的断言里，有多少能在参考断言中找到语义等价项
- `recall` = 参考断言里，有多少能被生成的断言覆盖到

**四级匹配等级（`match_level` 字段）**：

| match_level | 含义 | 判定条件 |
|---|---|---|
| `完全一致` | 生成断言与参考断言一一对应，无遗漏无多余 | fp=0 且 fn=0 |
| `生成用例是答案的子集` | 生成的每一条都能在参考里找到等价项，但参考里还有更多断言没被覆盖 | fp=0 且 fn>0 |
| `答案是生成用例的子集` | 参考的每一条都被生成覆盖了，但生成还多产出了参考里没有的断言 | fp>0 且 fn=0 |
| `不匹配` | 既有遗漏又有多余，两组断言对不上 | fp>0 且 fn>0 |

（fp = 生成中找不到对应参考项的断言数；fn = 参考中没被任何生成断言覆盖的断言数。`exact_match`
字段保留只是为了兼容旧代码，等价于 `match_level == "完全一致"`）

对于两边都判断为 `equivalent: None`（当前不支持建模的语法，如位运算）的断言对，会被单独收集在
每条用例结果的 `uncertain` 字段里，不计入匹配依据，建议转交LLM-as-judge或人工复核。

**⚠️ 关于自测的真实性说明**：`determine_match_level` 这个四级分类函数本身的逻辑我已经用真实单元
测试验证过（4种fp/fn组合都给出了正确的分类）。但用假的 z3 桩模块跑端到端测试时，因为桩模块永远
声称"等价"（不做真正的符号推理），会把本该判定为"不匹配"的用例误标成"完全一致"——**这是测试桩
本身的局限，不是分类逻辑或核心代码的bug**。请在装好真实 `z3-solver` 后重新跑一遍确认。


## 已知问题 / 踩过的坑

1. **pycparser 表达式提取的陷阱**：把表达式包进虚拟函数体解析后，`block_items[0]` 本身
   就是表达式的AST根节点（不会再包一层 ExprStmt），如果误用
   `getattr(stmt, "expr", stmt)` 去"兼容取值"，会在根节点恰好是 `UnaryOp`（比如 `!(...)`）
   时，把 `.expr` 属性（即操作数本身）误当成整个表达式，导致 `!` 被吞掉。已在
   `assertion_normalizer.py` 里改成直接使用 `body.block_items[0]`。
2. **`ASSERT_TRUE`/`ASSERT_FALSE` 类断言的参数可能内嵌关系表达式**：例如
   `TEST_ASSERT_TRUE(r == 5)` 语义上等价于 `CU_ASSERT_EQUAL(r, 5)`，代码里统一对
   TRUE/FALSE 参数也尝试用裸表达式解析来提取内嵌的关系运算符，能覆盖到很多这种情况。

## 当前实现覆盖范围 & 局限性

**已支持：**
- 常见测试框架的断言宏：CUnit、Check、Unity、CMocka，以及标准库 `assert()`
- 交换律、双重否定/取反关系运算符的结构归一化
- 四则运算、关系运算、逻辑运算、三元表达式、数组下标、结构体字段访问、类型转换
- 无法直接符号化的函数调用（如 `strcmp`、自定义函数）通过 Z3 的不确定函数（Uninterpreted
  Function）建模，保证"相同输入→相同输出"这一基本语义约束

**当前局限（建议下一步扩展的方向）：**
1. **变量同名假设**：目前假设两个断言里同名变量代表同一个语义对象。这在"同一测试函数内
   对比LLM生成断言与ground truth断言"的场景下通常成立，但如果LLM给变量起了不同的名字
   （比如 ground truth 用 `result`，LLM 生成用 `actual`），就需要先做变量名对齐/别名映射，
   否则会被误判为不等价。可以考虑：如果两个断言涉及的变量集合在程序里能追溯到同一个
   赋值来源（如通过被测函数调用返回值），则视为同一变量。
2. **浮点误差**：如果断言涉及 `fabs(a-b) < EPS` 这类近似相等判断，与 `a == b` 严格相等
   在数学上并不等价，Z3 会（正确地）判定为不等价，但从测试预言"意图相同"的角度，可能需要
   人工规则识别这种"近似相等模式"并特殊处理。
3. **位运算、宏常量**：位运算符（`&`, `|`, `^`, `<<`, `>>`）目前未加入 `_BIN_OP_MAP`，
   遇到时会抛 `NotImplementedError`，在 `pipeline.py` 里会被捕获并标记为
   `method: "unsupported"`（而不是直接误判为不等价），这类样本建议转交第4层
   LLM-as-judge 或人工复核。
4. **超出表达式级别的语义**（比如断言涉及函数调用的副作用顺序、多语句组合的预言逻辑）
   本方案不处理，需要更重的方案（比如之前建议的方案3：动态执行等价检测）。

## 建议的下一步

把 `pipeline.py` 里 `method == "unsupported"` 和 `equivalent is None` 的样本单独收集起来，
连同`method == "structural"/"smt"`但你人工抽查后发现误判的样本，一起交给LLM-as-judge兜底，
并做人工抽样标注计算一致率，这样论文里能清楚报告"自动化流程覆盖了多少比例、可信度如何"。
