#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
C First-Order Mutation Generator
================================
基于 Tree-sitter C 语法树生成一阶突变体（First-Order Mutants）。

支持算子：
    AOR      Arithmetic Operator Replacement
    ROR      Relational Operator Replacement
    LOR      Logical Operator Replacement
    BOR      Bitwise Operator Replacement
    SOR      Shift Operator Replacement
    CRP      Constant Replacement
    UOI/UOD  Unary Operator Insertion / Deletion
    ASR      Assignment Operator Replacement
    ICR      Increment/Decrement Replacement
    CNO      Condition Negation
    RVR      Return Value Replacement
    SDL      Statement Deletion

安装：
    pip install tree-sitter tree-sitter-c

示例：
    python mutation_tool.py D:\\project\\src\\foo.c
    python mutation_tool.py D:\\project\\src\\foo.c -o D:\\project\\mutants
    python mutation_tool.py foo.c --operators AOR,ROR,CNO,RVR
    python mutation_tool.py foo.c --max-per-operator 100

输出：
    mutants/
      M000001_AOR_L12.c
      M000002_ROR_L20.c
      ...
      mutants.json
      summary.json

说明：
1. 不修改原始 C 文件。
2. 每个 mutant 只包含一个修改，即 first-order mutation。
3. SDL 默认只删除 expression_statement，以减少大量无意义/不可编译突变。
4. 编译过滤、运行测试、Killed/Survived 判定建议放在独立执行器中完成。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Optional

from tree_sitter import Language, Parser
import tree_sitter_c

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

ALL_OPERATORS = {
    "AOR", "ROR", "LOR", "BOR", "SOR", "CRP",
    "UOI", "UOD", "ASR", "ICR", "CNO", "RVR", "SDL",
}

# 算子替换采用“同类其它算子”策略。
AOR_MAP = {
    "+": ["-", "*", "/", "%"],
    "-": ["+", "*", "/", "%"],
    "*": ["+", "-", "/", "%"],
    "/": ["+", "-", "*", "%"],
    "%": ["+", "-", "*", "/"],
}

ROR_MAP = {
    "<":  ["<=", ">", ">=", "==", "!="],
    "<=": ["<",  ">", ">=", "==", "!="],
    ">":  [">=", "<", "<=", "==", "!="],
    ">=": [">",  "<", "<=", "==", "!="],
    "==": ["!=", "<", "<=", ">", ">="],
    "!=": ["==", "<", "<=", ">", ">="],
}

LOR_MAP = {
    "&&": ["||"],
    "||": ["&&"],
}

BOR_MAP = {
    "&": ["|", "^"],
    "|": ["&", "^"],
    "^": ["&", "|"],
}

SOR_MAP = {
    "<<": [">>"],
    ">>": ["<<"],
}

ASR_MAP = {
    "=":   ["+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "<<=", ">>="],
    "+=":  ["-=", "*=", "/=", "%=", "="],
    "-=":  ["+=", "*=", "/=", "%=", "="],
    "*=":  ["/=", "+=", "-=", "="],
    "/=":  ["*=", "+=", "-=", "="],
    "%=":  ["+=", "-=", "*=", "/=", "="],
    "&=":  ["|=", "^=", "="],
    "|=":  ["&=", "^=", "="],
    "^=":  ["&=", "|=", "="],
    "<<=": [">>=", "="],
    ">>=": ["<<=", "="],
}

ICR_MAP = {
    "++": ["--"],
    "--": ["++"],
}

UOD_OPERATORS = {"!", "-", "+", "~"}
UOI_PREFIXES = ("!", "-", "~")

CONDITION_NODE_TYPES = {
    "if_statement",
    "while_statement",
    "do_statement",
    "for_statement",
}

# 对这些位置插入一元算子通常有较明确的语义。
UOI_PARENT_FIELDS = {
    "binary_expression": ("left", "right"),
    "assignment_expression": ("right",),
    "return_statement": (None,),
}

# C 整数字面量（覆盖常见 10/16/8/2 进制及 U/L 后缀）
INT_LITERAL_RE = re.compile(
    r"""(?ix)^
    (?P<sign>[+-]?)
    (?P<body>
        0[xX][0-9a-f]+ |
        0[bB][01]+ |
        0[0-7]+ |
        [0-9]+
    )
    (?P<suffix>(?:u|l|ul|lu|ll|ull|llu)*)$
    """
)

FLOAT_LITERAL_RE = re.compile(
    r"""(?ix)^
    (?P<number>
        (?:
            (?:[0-9]+\.[0-9]*|\.[0-9]+|[0-9]+)
            (?:[eE][+-]?[0-9]+)?
        )
        |
        (?:
            0[xX](?:[0-9a-f]+\.[0-9a-f]*|\.[0-9a-f]+|[0-9a-f]+)
            [pP][+-]?[0-9]+
        )
    )
    (?P<suffix>[fFlL]?)$
    """
)


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Mutation:
    operator: str
    start_byte: int
    end_byte: int
    replacement: str
    line: int
    column: int
    original: str
    description: str
    context: str

    def dedup_key(self) -> tuple:
        return (
            self.operator,
            self.start_byte,
            self.end_byte,
            self.replacement,
        )


@dataclass
class MutantRecord:
    mutant_id: str
    operator: str
    source_file: str
    output_file: str
    line: int
    column: int
    start_byte: int
    end_byte: int
    original: str
    replacement: str
    description: str
    context: str


# ---------------------------------------------------------------------------
# Tree-sitter 基础封装
# ---------------------------------------------------------------------------

class CMutationGenerator:
    def __init__(
        self,
        source_path: Path,
        enabled_operators: set[str],
        max_per_operator: int = 0,
    ) -> None:
        self.source_path = source_path.resolve()
        self.source = self.source_path.read_bytes()
        self.enabled = enabled_operators
        self.max_per_operator = max_per_operator

        language = Language(tree_sitter_c.language())
        self.parser = Parser(language)
        self.tree = self.parser.parse(self.source)

        self.mutations: list[Mutation] = []
        self._seen: set[tuple] = set()
        self._counts: Counter[str] = Counter()

    # -------------------------- 通用辅助函数 --------------------------

    def node_text(self, node) -> str:
        return self.source[node.start_byte:node.end_byte].decode(
            "utf-8", errors="replace"
        )

    @staticmethod
    def point_row_col(node) -> tuple[int, int]:
        p = node.start_point
        # 新版 tree-sitter 返回 Point(row=..., column=...)
        if hasattr(p, "row"):
            return int(p.row), int(p.column)
        # 兼容旧版 tuple
        return int(p[0]), int(p[1])

    def context_line(self, start_byte: int) -> str:
        before = self.source[:start_byte]
        line_start = before.rfind(b"\n") + 1
        line_end = self.source.find(b"\n", start_byte)
        if line_end < 0:
            line_end = len(self.source)
        return self.source[line_start:line_end].decode(
            "utf-8", errors="replace"
        ).rstrip("\r")

    def direct_operator_token(self, node, candidates: set[str]):
        """
        在节点的直接 children 中寻找匿名运算符 token。
        这样不会误把子表达式中的运算符当成当前节点运算符。
        """
        for child in node.children:
            text = self.node_text(child)
            if text in candidates:
                return child, text
        return None, None

    def add_mutation(
        self,
        operator: str,
        start_byte: int,
        end_byte: int,
        replacement: str,
        description: str,
    ) -> None:
        if operator not in self.enabled:
            return

        if self.max_per_operator > 0:
            if self._counts[operator] >= self.max_per_operator:
                return

        original = self.source[start_byte:end_byte].decode(
            "utf-8", errors="replace"
        )
        if original == replacement:
            return

        # 根据 byte offset 找行列；Tree-sitter 节点未必正好覆盖这个 token，
        # 因此直接从源码计算。
        prefix = self.source[:start_byte]
        line = prefix.count(b"\n") + 1
        last_nl = prefix.rfind(b"\n")
        column = start_byte if last_nl < 0 else start_byte - last_nl - 1

        mutation = Mutation(
            operator=operator,
            start_byte=start_byte,
            end_byte=end_byte,
            replacement=replacement,
            line=line,
            column=column,
            original=original,
            description=description,
            context=self.context_line(start_byte),
        )

        key = mutation.dedup_key()
        if key in self._seen:
            return

        self._seen.add(key)
        self.mutations.append(mutation)
        self._counts[operator] += 1

    # -------------------------- 运算符替换类 --------------------------

    def mutate_binary_operator(self, node) -> None:
        maps = [
            ("AOR", AOR_MAP),
            ("ROR", ROR_MAP),
            ("LOR", LOR_MAP),
            ("BOR", BOR_MAP),
            ("SOR", SOR_MAP),
        ]

        all_tokens: set[str] = set()
        for _, mapping in maps:
            all_tokens.update(mapping.keys())

        token_node, op = self.direct_operator_token(node, all_tokens)
        if token_node is None:
            return

        for mutation_name, mapping in maps:
            if mutation_name not in self.enabled:
                continue
            if op not in mapping:
                continue

            for replacement in mapping[op]:
                self.add_mutation(
                    mutation_name,
                    token_node.start_byte,
                    token_node.end_byte,
                    replacement,
                    f"{mutation_name}: {op} -> {replacement}",
                )

    def mutate_assignment(self, node) -> None:
        token_node, op = self.direct_operator_token(
            node, set(ASR_MAP.keys())
        )
        if token_node is None or op not in ASR_MAP:
            return

        for replacement in ASR_MAP[op]:
            self.add_mutation(
                "ASR",
                token_node.start_byte,
                token_node.end_byte,
                replacement,
                f"ASR: {op} -> {replacement}",
            )

    def mutate_update(self, node) -> None:
        token_node, op = self.direct_operator_token(
            node, set(ICR_MAP.keys())
        )
        if token_node is None or op not in ICR_MAP:
            return

        for replacement in ICR_MAP[op]:
            self.add_mutation(
                "ICR",
                token_node.start_byte,
                token_node.end_byte,
                replacement,
                f"ICR: {op} -> {replacement}",
            )

    # -------------------------- CRP --------------------------

    @staticmethod
    def parse_c_integer(text: str) -> Optional[tuple[int, str]]:
        m = INT_LITERAL_RE.match(text)
        if not m:
            return None

        body = m.group("body")
        suffix = m.group("suffix") or ""

        try:
            if body.lower().startswith("0x"):
                value = int(body, 16)
            elif body.lower().startswith("0b"):
                value = int(body, 2)
            elif len(body) > 1 and body.startswith("0"):
                value = int(body, 8)
            else:
                value = int(body, 10)
            return value, suffix
        except ValueError:
            return None

    @staticmethod
    def constant_replacements(text: str) -> list[str]:
        """
        常量替换：
          整数：0, 1, -1, x-1, x+1
          浮点：0.0, 1.0, -1.0
        为降低复杂度，生成值采用十进制表示；尽量保留 U/L/F 等后缀。
        """
        parsed = CMutationGenerator.parse_c_integer(text)
        if parsed is not None:
            value, suffix = parsed
            suffix_out = suffix

            candidates = [
                f"0{suffix_out}",
                f"1{suffix_out}",
            ]

            # unsigned 常量生成 -1U 虽合法但通常会变成最大无符号数，
            # 对 CRP 来说会制造非常极端的 mutation。这里仍允许，
            # 但只在原值不是无符号时默认加入 -1。
            if "u" not in suffix.lower():
                candidates.append(f"-1{suffix_out}")

            candidates.extend([
                f"{value - 1}{suffix_out}",
                f"{value + 1}{suffix_out}",
            ])

            return list(dict.fromkeys(x for x in candidates if x != text))

        if FLOAT_LITERAL_RE.match(text):
            suffix = text[-1] if text[-1:] in "fFlL" else ""
            candidates = [
                f"0.0{suffix}",
                f"1.0{suffix}",
                f"-1.0{suffix}",
            ]
            return [x for x in candidates if x != text]

        return []

    def mutate_constant(self, node) -> None:
        text = self.node_text(node)

        for replacement in self.constant_replacements(text):
            self.add_mutation(
                "CRP",
                node.start_byte,
                node.end_byte,
                replacement,
                f"CRP: {text} -> {replacement}",
            )

    # -------------------------- UOI / UOD --------------------------

    def mutate_unary_deletion(self, node) -> None:
        token_node, op = self.direct_operator_token(
            node, UOD_OPERATORS
        )
        if token_node is None:
            return

        self.add_mutation(
            "UOD",
            token_node.start_byte,
            token_node.end_byte,
            "",
            f"UOD: delete unary operator {op}",
        )

    def add_uoi_to_expression(self, expr) -> None:
        if expr is None:
            return

        # 避免对完整 unary_expression 再无限套娃。
        if expr.type == "unary_expression":
            return

        original = self.node_text(expr)
        if not original.strip():
            return

        for prefix in UOI_PREFIXES:
            # 加括号，避免改变原表达式结合关系之外的额外语法问题。
            replacement = f"{prefix}({original})"
            self.add_mutation(
                "UOI",
                expr.start_byte,
                expr.end_byte,
                replacement,
                f"UOI: insert unary operator {prefix}",
            )

    def mutate_uoi_from_parent(self, node) -> None:
        """
        只在具有明确“值表达式”语义的位置插入一元算子，
        避免给函数名、结构体成员名、声明符等乱加前缀。
        """
        if "UOI" not in self.enabled:
            return

        if node.type == "binary_expression":
            self.add_uoi_to_expression(node.child_by_field_name("left"))
            self.add_uoi_to_expression(node.child_by_field_name("right"))

        elif node.type == "assignment_expression":
            self.add_uoi_to_expression(node.child_by_field_name("right"))

        elif node.type == "return_statement":
            # return_statement 通常只有一个 named child 为返回表达式
            if node.named_child_count > 0:
                self.add_uoi_to_expression(node.named_children[0])

    # -------------------------- CNO --------------------------

    def mutate_condition_negation(self, node) -> None:
        if node.type not in CONDITION_NODE_TYPES:
            return

        condition = node.child_by_field_name("condition")
        if condition is None:
            return

        text = self.node_text(condition)
        replacement = f"!({text})"

        self.add_mutation(
            "CNO",
            condition.start_byte,
            condition.end_byte,
            replacement,
            f"CNO: negate condition `{text}`",
        )

    # -------------------------- RVR --------------------------

    def mutate_return_value(self, node) -> None:
        if node.type != "return_statement":
            return
        if node.named_child_count == 0:
            # return;
            return

        expr = node.named_children[0]
        original = self.node_text(expr)

        # 使用较通用的替换；编译过滤阶段会自然去掉类型不兼容 mutant。
        candidates = ["0", "1", "-1"]

        for replacement in candidates:
            if replacement == original.strip():
                continue
            self.add_mutation(
                "RVR",
                expr.start_byte,
                expr.end_byte,
                replacement,
                f"RVR: return {original} -> return {replacement}",
            )

    # -------------------------- SDL --------------------------

    def mutate_statement_deletion(self, node) -> None:
        """
        删除 expression_statement。
        典型覆盖：
            x = y;
            x++;
            foo();
            reg |= MASK;

        不默认删除 declaration / return / if / loop，
        因为这些删除很容易产生大量不可编译或结构破坏的 mutant。
        """
        if node.type != "expression_statement":
            return

        original = self.node_text(node)

        # 用空语句替换，而不是完全删除：
        # 1) 对 if (...) stmt; 这类位置仍保持语法合法；
        # 2) 对普通 block 中表达式语句等价于删除其副作用。
        self.add_mutation(
            "SDL",
            node.start_byte,
            node.end_byte,
            ";",
            f"SDL: delete statement `{original.strip()}`",
        )

    # -------------------------- 遍历 --------------------------

    def visit(self, node) -> None:
        if node.type == "binary_expression":
            self.mutate_binary_operator(node)

        if node.type == "assignment_expression":
            self.mutate_assignment(node)

        if node.type == "update_expression":
            self.mutate_update(node)

        if node.type in {"number_literal"}:
            self.mutate_constant(node)

        if node.type == "unary_expression":
            self.mutate_unary_deletion(node)

        self.mutate_uoi_from_parent(node)
        self.mutate_condition_negation(node)
        self.mutate_return_value(node)
        self.mutate_statement_deletion(node)

        for child in node.named_children:
            self.visit(child)

    def collect(self) -> list[Mutation]:
        self.visit(self.tree.root_node)

        # 固定排序保证实验可复现
        self.mutations.sort(
            key=lambda m: (
                m.start_byte,
                m.end_byte,
                m.operator,
                m.replacement,
            )
        )
        return self.mutations


# ---------------------------------------------------------------------------
# 文件生成
# ---------------------------------------------------------------------------

def apply_mutation(source: bytes, mutation: Mutation) -> bytes:
    replacement_bytes = mutation.replacement.encode("utf-8")
    return (
        source[:mutation.start_byte]
        + replacement_bytes
        + source[mutation.end_byte:]
    )


def sanitize_name(text: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", text)
    return text.strip("_") or "source"


def generate_mutant_files(
    source_path: Path,
    output_dir: Path,
    mutations: Iterable[Mutation],
) -> list[MutantRecord]:
    source = source_path.read_bytes()
    output_dir.mkdir(parents=True, exist_ok=True)

    records: list[MutantRecord] = []
    stem = sanitize_name(source_path.stem)

    for index, mutation in enumerate(mutations, start=1):
        mutant_id = f"M{index:06d}"
        filename = (
            f"{mutant_id}_{mutation.operator}_"
            f"L{mutation.line}_{stem}.c"
        )
        mutant_path = output_dir / filename

        mutant_source = apply_mutation(source, mutation)
        mutant_path.write_bytes(mutant_source)

        record = MutantRecord(
            mutant_id=mutant_id,
            operator=mutation.operator,
            source_file=str(source_path.resolve()),
            output_file=str(mutant_path.resolve()),
            line=mutation.line,
            column=mutation.column,
            start_byte=mutation.start_byte,
            end_byte=mutation.end_byte,
            original=mutation.original,
            replacement=mutation.replacement,
            description=mutation.description,
            context=mutation.context,
        )
        records.append(record)

    return records


def write_metadata(
    output_dir: Path,
    records: list[MutantRecord],
    enabled_operators: set[str],
) -> None:
    mutants_json = output_dir / "mutants.json"
    summary_json = output_dir / "summary.json"

    mutants_json.write_text(
        json.dumps(
            [asdict(record) for record in records],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    counts = Counter(record.operator for record in records)
    summary = {
        "total_mutants": len(records),
        "enabled_operators": sorted(enabled_operators),
        "counts_by_operator": {
            op: counts.get(op, 0)
            for op in sorted(enabled_operators)
        },
    }

    summary_json.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_operator_list(text: str) -> set[str]:
    if text.strip().lower() == "all":
        return set(ALL_OPERATORS)

    result: set[str] = set()

    for item in text.split(","):
        item = item.strip().upper()
        if not item:
            continue

        # 允许用户写 UOI/UOD
        if item == "UOI/UOD":
            result.update({"UOI", "UOD"})
        else:
            result.add(item)

    unknown = result - ALL_OPERATORS
    if unknown:
        raise argparse.ArgumentTypeError(
            "未知 mutation operator: "
            + ", ".join(sorted(unknown))
        )

    if not result:
        raise argparse.ArgumentTypeError("至少选择一个 mutation operator")

    return result


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate first-order mutants for a C source file."
    )
    parser.add_argument(
        "source",
        type=Path,
        help="输入 C 文件路径",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="mutant 输出目录；默认：<源文件目录>/<源文件名>_mutants",
    )
    parser.add_argument(
        "--operators",
        type=parse_operator_list,
        default=set(ALL_OPERATORS),
        help=(
            "启用算子，逗号分隔。"
            "例如 AOR,ROR,CNO,RVR；默认 all"
        ),
    )
    parser.add_argument(
        "--max-per-operator",
        type=int,
        default=0,
        help="每类算子最多生成多少个 mutant；0 表示不限制",
    )
    return parser


def main() -> int:
    parser = build_argument_parser()
    args = parser.parse_args()

    source_path: Path = args.source
    if not source_path.exists():
        parser.error(f"C 文件不存在：{source_path}")
    if not source_path.is_file():
        parser.error(f"输入不是文件：{source_path}")
    if source_path.suffix.lower() != ".c":
        parser.error("输入文件必须是 .c 文件")
    if args.max_per_operator < 0:
        parser.error("--max-per-operator 不能小于 0")

    output_dir = (
        args.output
        if args.output is not None
        else source_path.parent / f"{source_path.stem}_mutants"
    )

    generator = CMutationGenerator(
        source_path=source_path,
        enabled_operators=args.operators,
        max_per_operator=args.max_per_operator,
    )

    mutations = generator.collect()

    records = generate_mutant_files(
        source_path,
        output_dir,
        mutations,
    )
    write_metadata(
        output_dir,
        records,
        args.operators,
    )

    counts = Counter(record.operator for record in records)

    print("=" * 68)
    print("C Mutation Generation Finished")
    print("=" * 68)
    print(f"Source : {source_path.resolve()}")
    print(f"Output : {output_dir.resolve()}")
    print(f"Total  : {len(records)}")
    print()

    for op in sorted(args.operators):
        print(f"{op:4s}: {counts.get(op, 0)}")

    print()
    print(f"Metadata: {(output_dir / 'mutants.json').resolve()}")
    print(f"Summary : {(output_dir / 'summary.json').resolve()}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
