# -*- coding: utf-8 -*-
"""Assertion extraction and conservative normalization for C unit-test oracles."""

import ast as py_ast
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import List, Optional, Tuple, Any

from pycparser import c_ast, c_parser, c_generator


# op, minimum arity.  The first two arguments are used as operands unless a
# special operator below says otherwise.  Equality operators are symmetric, so
# expected/actual argument order does not affect equivalence.
ASSERTION_MACROS = {
    # CUnit
    "CU_ASSERT_EQUAL": ("EQ", 2),
    "CU_ASSERT_NOT_EQUAL": ("NE", 2),
    "CU_ASSERT_TRUE": ("TRUE", 1),
    "CU_ASSERT_FALSE": ("FALSE", 1),
    "CU_ASSERT_PTR_NULL": ("NULL", 1),
    "CU_ASSERT_PTR_NOT_NULL": ("NOTNULL", 1),
    "CU_ASSERT_STRING_EQUAL": ("STREQ", 2),
    "CU_ASSERT_DOUBLE_EQUAL": ("WITHIN_CUNIT", 3),

    # Check
    "ck_assert_int_eq": ("EQ", 2),
    "ck_assert_int_ne": ("NE", 2),
    "ck_assert_int_lt": ("LT", 2),
    "ck_assert_int_le": ("LE", 2),
    "ck_assert_int_gt": ("GT", 2),
    "ck_assert_int_ge": ("GE", 2),
    "ck_assert_str_eq": ("STREQ", 2),
    "ck_assert_str_ne": ("STRNE", 2),
    "ck_assert_ptr_null": ("NULL", 1),
    "ck_assert_ptr_nonnull": ("NOTNULL", 1),
    "ck_assert": ("TRUE", 1),

    # Unity scalar equality
    "TEST_ASSERT_EQUAL": ("EQ", 2),
    "TEST_ASSERT_NOT_EQUAL": ("NE", 2),
    "TEST_ASSERT_EQUAL_INT": ("EQ", 2),
    "TEST_ASSERT_EQUAL_INT8": ("EQ", 2),
    "TEST_ASSERT_EQUAL_INT16": ("EQ", 2),
    "TEST_ASSERT_EQUAL_INT32": ("EQ", 2),
    "TEST_ASSERT_EQUAL_INT64": ("EQ", 2),
    "TEST_ASSERT_EQUAL_UINT": ("EQ", 2),
    "TEST_ASSERT_EQUAL_UINT8": ("EQ", 2),
    "TEST_ASSERT_EQUAL_UINT16": ("EQ", 2),
    "TEST_ASSERT_EQUAL_UINT32": ("EQ", 2),
    "TEST_ASSERT_EQUAL_UINT64": ("EQ", 2),
    "TEST_ASSERT_EQUAL_HEX8": ("EQ", 2),
    "TEST_ASSERT_EQUAL_HEX16": ("EQ", 2),
    "TEST_ASSERT_EQUAL_HEX32": ("EQ", 2),
    "TEST_ASSERT_EQUAL_HEX64": ("EQ", 2),
    "TEST_ASSERT_EQUAL_CHAR": ("EQ", 2),
    "TEST_ASSERT_EQUAL_DOUBLE": ("EQ", 2),
    "TEST_ASSERT_EQUAL_FLOAT": ("EQ", 2),
    "TEST_ASSERT_FLOAT_EQUAL": ("EQ", 2),
    "TEST_ASSERT_EQUAL_PTR": ("EQ", 2),
    "TEST_ASSERT_EQUAL_STRING": ("STREQ", 2),

    # Unity truth/null
    "TEST_ASSERT_TRUE": ("TRUE", 1),
    "TEST_ASSERT_FALSE": ("FALSE", 1),
    "TEST_ASSERT_NULL": ("NULL", 1),
    "TEST_ASSERT_NOT_NULL": ("NOTNULL", 1),
    "TEST_ASSERT_PASS": ("PASS", 0),

    # Unity comparisons.  Unity's first argument is a threshold and the second
    # is the actual value, so the directional relation is actual OP threshold.
    "TEST_ASSERT_GREATER_THAN": ("GT_REV", 2),
    "TEST_ASSERT_GREATER_OR_EQUAL": ("GE_REV", 2),
    "TEST_ASSERT_LESS_THAN": ("LT_REV", 2),
    "TEST_ASSERT_LESS_OR_EQUAL": ("LE_REV", 2),
    "TEST_ASSERT_GREATER_THAN_FLOAT": ("GT_REV", 2),
    "TEST_ASSERT_GREATER_OR_EQUAL_FLOAT": ("GE_REV", 2),
    "TEST_ASSERT_LESS_THAN_FLOAT": ("LT_REV", 2),
    "TEST_ASSERT_LESS_OR_EQUAL_FLOAT": ("LE_REV", 2),

    # Unity tolerance comparisons: delta, expected, actual
    "TEST_ASSERT_FLOAT_WITHIN": ("WITHIN", 3),
    "TEST_ASSERT_DOUBLE_WITHIN": ("WITHIN", 3),

    # Array/memory assertions are preserved as ternary relations.  They are not
    # collapsed to two operands, which was a source of false positives.
    "TEST_ASSERT_EQUAL_UINT8_ARRAY": ("ARREQ", 3),
    "TEST_ASSERT_EQUAL_UINT16_ARRAY": ("ARREQ", 3),
    "TEST_ASSERT_EQUAL_UINT32_ARRAY": ("ARREQ", 3),
    "TEST_ASSERT_EQUAL_UINT64_ARRAY": ("ARREQ", 3),
    "TEST_ASSERT_EQUAL_INT8_ARRAY": ("ARREQ", 3),
    "TEST_ASSERT_EQUAL_INT16_ARRAY": ("ARREQ", 3),
    "TEST_ASSERT_EQUAL_INT32_ARRAY": ("ARREQ", 3),
    "TEST_ASSERT_EQUAL_INT64_ARRAY": ("ARREQ", 3),
    "TEST_ASSERT_EQUAL_HEX8_ARRAY": ("ARREQ", 3),
    "TEST_ASSERT_EQUAL_HEX16_ARRAY": ("ARREQ", 3),
    "TEST_ASSERT_EQUAL_HEX32_ARRAY": ("ARREQ", 3),
    "TEST_ASSERT_EQUAL_HEX64_ARRAY": ("ARREQ", 3),
    "TEST_ASSERT_EQUAL_FLOAT_ARRAY": ("ARREQ", 3),
    "TEST_ASSERT_EQUAL_DOUBLE_ARRAY": ("ARREQ", 3),
    "TEST_ASSERT_EQUAL_MEMORY": ("MEMEQ", 3),
    "TEST_ASSERT_EACH_EQUAL_HEX8": ("EACHEQ", 3),
    "TEST_ASSERT_EACH_EQUAL_HEX16": ("EACHEQ", 3),
    "TEST_ASSERT_EACH_EQUAL_HEX32": ("EACHEQ", 3),
    "TEST_ASSERT_EACH_EQUAL_UINT8": ("EACHEQ", 3),
    "TEST_ASSERT_EACH_EQUAL_UINT16": ("EACHEQ", 3),
    "TEST_ASSERT_EACH_EQUAL_UINT32": ("EACHEQ", 3),
    "TEST_ASSERT_BITS_HIGH": ("BITS_HIGH", 2),

    # Unity internal macros that occasionally leak into model output.  Trailing
    # line/message arguments are metadata and deliberately ignored.
    "UNITY_TEST_ASSERT_EQUAL_UINT8": ("EQ", 2),
    "UNITY_TEST_ASSERT_EQUAL_UINT16": ("EQ", 2),
    "UNITY_TEST_ASSERT_EQUAL_UINT32": ("EQ", 2),
    "UNITY_TEST_ASSERT_EQUAL_INT": ("EQ", 2),

    # Project-specific assertion seen in the validation corpus.
    "CHECK_EQ_32": ("EQ", 2),

    # CMocka
    "assert_int_equal": ("EQ", 2),
    "assert_int_not_equal": ("NE", 2),
    "assert_true": ("TRUE", 1),
    "assert_false": ("FALSE", 1),
    "assert_null": ("NULL", 1),
    "assert_non_null": ("NOTNULL", 1),
    "assert_string_equal": ("STREQ", 2),

    # standard/custom raw predicates
    "assert": ("RAW", 1),
    "CHECK": ("RAW", 1),
    "REQUIRE": ("RAW", 1),
    "EXPECT": ("RAW", 1),
    "ASSERT": ("RAW", 1),
}



def _looks_like_assertion_name(name: str) -> bool:
    return (
        name in {"assert", "CHECK", "REQUIRE", "EXPECT", "ASSERT"}
        or name.startswith(("TEST_ASSERT", "UNITY_TEST_ASSERT", "CU_ASSERT", "ck_assert", "assert_", "CHECK_"))
    )

def register_macro(name: str, op: str, arity: int) -> None:
    ASSERTION_MACROS[name] = (op, arity)


@dataclass
class NormalizedAssertion:
    op: str
    lhs: Optional[str]
    rhs: Optional[str]
    raw_macro: str
    raw_args: List[str]


# ----------------------------- lexical helpers -----------------------------

def split_args(arg_str: str) -> List[str]:
    """Split comma-separated arguments while respecting nesting and literals."""
    args, current = [], []
    depth = 0
    state = "normal"
    i = 0
    while i < len(arg_str):
        ch = arg_str[i]
        nxt = arg_str[i + 1] if i + 1 < len(arg_str) else ""
        if state == "string":
            current.append(ch)
            if ch == "\\" and i + 1 < len(arg_str):
                current.append(arg_str[i + 1]); i += 2; continue
            if ch == '"': state = "normal"
        elif state == "char":
            current.append(ch)
            if ch == "\\" and i + 1 < len(arg_str):
                current.append(arg_str[i + 1]); i += 2; continue
            if ch == "'": state = "normal"
        elif state == "line_comment":
            if ch == "\n": state = "normal"; current.append(" ")
        elif state == "block_comment":
            if ch == "*" and nxt == "/": state = "normal"; current.append(" "); i += 2; continue
        else:
            if ch == '"': state = "string"; current.append(ch)
            elif ch == "'": state = "char"; current.append(ch)
            elif ch == "/" and nxt == "/": state = "line_comment"; i += 2; continue
            elif ch == "/" and nxt == "*": state = "block_comment"; i += 2; continue
            elif ch in "([{": depth += 1; current.append(ch)
            elif ch in ")]}": depth -= 1; current.append(ch)
            elif ch == "," and depth == 0:
                args.append("".join(current).strip()); current = []
            else: current.append(ch)
        i += 1
    tail = "".join(current).strip()
    if tail: args.append(tail)
    return args


def _scan_call_end(source: str, open_pos: int) -> Optional[int]:
    depth = 0
    state = "normal"
    i = open_pos
    while i < len(source):
        ch = source[i]
        nxt = source[i + 1] if i + 1 < len(source) else ""
        if state == "string":
            if ch == "\\" and i + 1 < len(source): i += 2; continue
            if ch == '"': state = "normal"
        elif state == "char":
            if ch == "\\" and i + 1 < len(source): i += 2; continue
            if ch == "'": state = "normal"
        elif state == "line_comment":
            if ch == "\n": state = "normal"
        elif state == "block_comment":
            if ch == "*" and nxt == "/": state = "normal"; i += 2; continue
        else:
            if ch == '"': state = "string"
            elif ch == "'": state = "char"
            elif ch == "/" and nxt == "/": state = "line_comment"; i += 2; continue
            elif ch == "/" and nxt == "*": state = "block_comment"; i += 2; continue
            elif ch == "(": depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0: return i
        i += 1
    return None


def extract_assertion_calls(source: str) -> List[Tuple[str, List[str]]]:
    """Extract registered assertion calls, excluding comments/string literals."""
    results = []
    i, n = 0, len(source or "")
    state = "normal"
    while i < n:
        ch = source[i]
        nxt = source[i + 1] if i + 1 < n else ""
        if state == "string":
            if ch == "\\" and i + 1 < n: i += 2; continue
            if ch == '"': state = "normal"
            i += 1; continue
        if state == "char":
            if ch == "\\" and i + 1 < n: i += 2; continue
            if ch == "'": state = "normal"
            i += 1; continue
        if state == "line_comment":
            if ch == "\n": state = "normal"
            i += 1; continue
        if state == "block_comment":
            if ch == "*" and nxt == "/": state = "normal"; i += 2; continue
            i += 1; continue

        if ch == '"': state = "string"; i += 1; continue
        if ch == "'": state = "char"; i += 1; continue
        if ch == "/" and nxt == "/": state = "line_comment"; i += 2; continue
        if ch == "/" and nxt == "*": state = "block_comment"; i += 2; continue

        if ch.isalpha() or ch == "_":
            j = i + 1
            while j < n and (source[j].isalnum() or source[j] == "_"): j += 1
            name = source[i:j]
            if name in ASSERTION_MACROS or _looks_like_assertion_name(name):
                k = j
                while k < n and source[k].isspace(): k += 1
                if k < n and source[k] == "(":
                    end = _scan_call_end(source, k)
                    if end is not None:
                        results.append((name, split_args(source[k + 1:end])))
                        i = end + 1
                        continue
            i = j; continue
        i += 1
    return results


# ------------------------------ C expression -------------------------------
_parser = c_parser.CParser()
_generator = c_generator.CGenerator()


def parse_c_expr(expr: str) -> Optional[c_ast.Node]:
    if expr is None: return None
    wrapper = "void __dummy(void) { (%s); }" % expr
    try:
        ast = _parser.parse(wrapper, filename="<expr>")
    except Exception:
        return None
    body = ast.ext[0].body
    return body.block_items[0] if body.block_items else None


def c_ast_to_str(node: c_ast.Node) -> str:
    return _generator.visit(node)


_BINOP_TO_OP = {"==": "EQ", "!=": "NE", "<": "LT", "<=": "LE", ">": "GT", ">=": "GE"}
_OP_NEGATION = {"EQ": "NE", "NE": "EQ", "LT": "GE", "GE": "LT", "LE": "GT", "GT": "LE"}


def resolve_raw_expr(expr_ast: c_ast.Node) -> Tuple[str, Optional[c_ast.Node], Optional[c_ast.Node]]:
    node = expr_ast
    negate = False
    while isinstance(node, c_ast.UnaryOp) and node.op == "!":
        negate = not negate; node = node.expr
    if isinstance(node, c_ast.BinaryOp) and node.op in _BINOP_TO_OP:
        op = _BINOP_TO_OP[node.op]
        if negate: op = _OP_NEGATION[op]
        return op, node.left, node.right
    return ("FALSE" if negate else "TRUE"), node, None


def normalize(macro_name: str, args: List[str]) -> Optional[NormalizedAssertion]:
    spec = ASSERTION_MACROS.get(macro_name)
    if spec is None:
        if _looks_like_assertion_name(macro_name):
            return NormalizedAssertion("UNKNOWN", macro_name, None, macro_name, args)
        return None
    op, arity = spec
    if len(args) < arity: return None

    if op == "PASS":
        return NormalizedAssertion("PASS", None, None, macro_name, args)
    if op == "RAW":
        expr_ast = parse_c_expr(args[0])
        if expr_ast is None:
            # Preserve as an opaque predicate rather than pretending parsing succeeded.
            return NormalizedAssertion("PRED", args[0], None, macro_name, args)
        real_op, lhs_ast, rhs_ast = resolve_raw_expr(expr_ast)
        return NormalizedAssertion(real_op,
                                   c_ast_to_str(lhs_ast) if lhs_ast is not None else None,
                                   c_ast_to_str(rhs_ast) if rhs_ast is not None else None,
                                   macro_name, args)
    if op in ("TRUE", "FALSE"):
        expr_ast = parse_c_expr(args[0])
        if expr_ast is not None:
            real_op, lhs_ast, rhs_ast = resolve_raw_expr(expr_ast)
            if op == "FALSE":
                if real_op in _OP_NEGATION: real_op = _OP_NEGATION[real_op]
                elif real_op == "TRUE": real_op = "FALSE"
                elif real_op == "FALSE": real_op = "TRUE"
            return NormalizedAssertion(real_op,
                                       c_ast_to_str(lhs_ast) if lhs_ast is not None else None,
                                       c_ast_to_str(rhs_ast) if rhs_ast is not None else None,
                                       macro_name, args)
        return NormalizedAssertion(op, args[0], None, macro_name, args)
    if op.endswith("_REV"):
        real = op[:-4]
        return NormalizedAssertion(real, args[1], args[0], macro_name, args)
    if op == "WITHIN":
        # Keep delta in raw_args; lhs/rhs are actual/expected for readability.
        return NormalizedAssertion("WITHIN", args[2], args[1], macro_name, args)
    if op == "WITHIN_CUNIT":
        # CUnit: actual, expected, granularity
        return NormalizedAssertion("WITHIN", args[0], args[1], macro_name, args)
    if op in ("ARREQ", "MEMEQ", "EACHEQ"):
        return NormalizedAssertion(op, args[0], args[1], macro_name, args)
    if arity == 1:
        return NormalizedAssertion(op, args[0], None, macro_name, args)
    return NormalizedAssertion(op, args[0], args[1], macro_name, args)


# -------------------------- structural canonicalizer -----------------------

def _parse_int_literal(v: str) -> Optional[int]:
    s = re.sub(r"[uUlL]+$", "", v.strip())
    try:
        if re.match(r"^0[0-7]+$", s): return int(s, 8)
        return int(s, 0)
    except Exception:
        return None


def _const_value(node: c_ast.Constant):
    if "int" in node.type or node.type in ("long", "unsigned long"):
        v = _parse_int_literal(node.value)
        return ("num", v) if v is not None else ("const", node.type, node.value)
    if node.type in ("float", "double"):
        s = re.sub(r"[fFlL]+$", "", node.value)
        try: return ("real", str(Decimal(s).normalize()))
        except InvalidOperation: return ("const", node.type, node.value)
    if node.type == "char":
        try: return ("num", ord(py_ast.literal_eval(node.value)))
        except Exception: return ("char", node.value)
    if node.type == "string":
        return ("string", node.value)
    return ("const", node.type, node.value)


def _fold_binary(op: str, l, r):
    if not (isinstance(l, tuple) and isinstance(r, tuple) and l[:1] == ("num",) and r[:1] == ("num",)):
        return None
    a, b = l[1], r[1]
    try:
        if op == "+": return ("num", a + b)
        if op == "-": return ("num", a - b)
        if op == "*": return ("num", a * b)
        if op == "/" and b != 0: return ("num", int(a / b))
        if op == "%" and b != 0: return ("num", a % b)
        if op == "<<": return ("num", a << b)
        if op == ">>": return ("num", a >> b)
        if op == "&": return ("num", a & b)
        if op == "|": return ("num", a | b)
        if op == "^": return ("num", a ^ b)
    except Exception:
        pass
    return None


def _canon_node(node: c_ast.Node):
    if isinstance(node, c_ast.Constant): return _const_value(node)
    if isinstance(node, c_ast.ID):
        if node.name == "true": return ("bool", True)
        if node.name == "false": return ("bool", False)
        return ("id", node.name)
    if isinstance(node, c_ast.UnaryOp):
        e = _canon_node(node.expr)
        if node.op == "+": return e
        if node.op == "-" and isinstance(e, tuple) and e[:1] == ("num",): return ("num", -e[1])
        return ("unary", node.op, e)
    if isinstance(node, c_ast.BinaryOp):
        l, r = _canon_node(node.left), _canon_node(node.right)
        folded = _fold_binary(node.op, l, r)
        if folded is not None: return folded
        zero, one = ("num", 0), ("num", 1)
        if node.op == "+" and r == zero: return l
        if node.op == "+" and l == zero: return r
        if node.op == "-" and r == zero: return l
        if node.op == "*" and r == one: return l
        if node.op == "*" and l == one: return r
        if node.op in ("+", "*", "&", "|", "^", "==", "!="):
            lr = sorted((l, r), key=repr); l, r = lr[0], lr[1]
        return ("bin", node.op, l, r)
    if isinstance(node, c_ast.ArrayRef): return ("arr", _canon_node(node.name), _canon_node(node.subscript))
    if isinstance(node, c_ast.StructRef): return ("field", node.type, _canon_node(node.name), node.field.name)
    if isinstance(node, c_ast.FuncCall):
        name = _canon_node(node.name)
        args = tuple(_canon_node(x) for x in (node.args.exprs if node.args else []))
        return ("call", name, args)
    if isinstance(node, c_ast.Cast):
        # Keep current project's historical policy: value-preserving cast is ignored
        # for structural oracle matching.  The SMT layer remains conservative.
        return _canon_node(node.expr)
    if isinstance(node, c_ast.TernaryOp):
        return ("ternary", _canon_node(node.cond), _canon_node(node.iftrue), _canon_node(node.iffalse))
    if isinstance(node, c_ast.CompoundLiteral):
        vals = tuple(_canon_node(x) for x in (node.init.exprs if isinstance(node.init, c_ast.InitList) else []))
        return ("compound", vals)
    if isinstance(node, c_ast.ExprList): return ("exprlist", tuple(_canon_node(x) for x in node.exprs))
    return ("rawast", _generator.visit(node))


def canonical_expr(s: Optional[str]):
    if s is None: return None
    node = parse_c_expr(s)
    if node is not None:
        try: return _canon_node(node)
        except Exception: pass
    # Fallback removes whitespace only outside string/char literals.
    out, state, i = [], "normal", 0
    while i < len(s):
        ch = s[i]
        if state == "string":
            out.append(ch)
            if ch == "\\" and i + 1 < len(s): out.append(s[i + 1]); i += 2; continue
            if ch == '"': state = "normal"
        elif state == "char":
            out.append(ch)
            if ch == "\\" and i + 1 < len(s): out.append(s[i + 1]); i += 2; continue
            if ch == "'": state = "normal"
        else:
            if ch == '"': state = "string"; out.append(ch)
            elif ch == "'": state = "char"; out.append(ch)
            elif not ch.isspace(): out.append(ch)
        i += 1
    return ("text", "".join(out))


def _expr_equal(a: Optional[str], b: Optional[str]) -> bool:
    return canonical_expr(a) == canonical_expr(b)


def _is_zero(s: Optional[str]) -> bool:
    return canonical_expr(s) == ("num", 0)


def _is_bool_literal(s: Optional[str], val: bool) -> bool:
    return canonical_expr(s) == ("bool", val)


_SYMMETRIC_OPS = {"EQ", "NE", "STREQ", "STRNE"}
_SWAP_OP = {"LT": "GT", "GT": "LT", "LE": "GE", "GE": "LE"}


def _simple_bool_relation(a: NormalizedAssertion):
    """Map TRUE/FALSE/NULL forms to comparable relation forms when sound."""
    if a.op == "NULL": return ("EQ", a.lhs, "0")
    if a.op == "NOTNULL": return ("NE", a.lhs, "0")
    if a.op == "FALSE": return ("EQ", a.lhs, "0")
    if a.op == "TRUE": return ("NE", a.lhs, "0")
    if a.op == "EQ":
        if _is_bool_literal(a.lhs, True): return ("BOOLTRUE", a.rhs, None)
        if _is_bool_literal(a.rhs, True): return ("BOOLTRUE", a.lhs, None)
        if _is_bool_literal(a.lhs, False): return ("EQ", a.rhs, "0")
        if _is_bool_literal(a.rhs, False): return ("EQ", a.lhs, "0")
    return (a.op, a.lhs, a.rhs)


def structurally_equal(a: NormalizedAssertion, b: NormalizedAssertion) -> bool:
    # Special ternary/opaque relations must retain their third semantic argument.
    # MEMORY vs typed ARRAY can denote the same sequence equality.  We only bridge
    # them when the expected/actual operands are identical and the memory extent is
    # expressed as sizeof(expected), or the explicit lengths are identical.
    if a.op in ("ARREQ", "MEMEQ") and b.op in ("ARREQ", "MEMEQ"):
        if not (_expr_equal(a.lhs, b.lhs) and _expr_equal(a.rhs, b.rhs)):
            return False
        if len(a.raw_args) < 3 or len(b.raw_args) < 3:
            return False
        if a.op == b.op:
            return _expr_equal(a.raw_args[2], b.raw_args[2])
        mem = a if a.op == "MEMEQ" else b
        arr = b if a.op == "MEMEQ" else a
        if _expr_equal(mem.raw_args[2], arr.raw_args[2]):
            return True
        mem_len = re.sub(r"\s+", "", mem.raw_args[2])
        lhs_compact = re.sub(r"\s+", "", mem.lhs or "")
        return mem_len in {f"sizeof({lhs_compact})", f"sizeof{lhs_compact}"}
    if a.op in ("EACHEQ", "WITHIN") or b.op in ("EACHEQ", "WITHIN"):
        if a.op != b.op: return False
        if not (_expr_equal(a.lhs, b.lhs) and _expr_equal(a.rhs, b.rhs)): return False
        if len(a.raw_args) < 3 or len(b.raw_args) < 3: return False
        if a.op == "WITHIN":
            def delta(x):
                return x.raw_args[0] if x.raw_macro.startswith("TEST_ASSERT_") else x.raw_args[2]
            return _expr_equal(delta(a), delta(b))
        return _expr_equal(a.raw_args[2], b.raw_args[2])
    if a.op in ("PASS", "BITS_HIGH", "PRED", "UNKNOWN") or b.op in ("PASS", "BITS_HIGH", "PRED", "UNKNOWN"):
        if a.op != b.op: return False
        if a.op == "UNKNOWN":
            return a.raw_macro == b.raw_macro and len(a.raw_args) == len(b.raw_args) and all(_expr_equal(x, y) for x, y in zip(a.raw_args, b.raw_args))
        return _expr_equal(a.lhs, b.lhs) and _expr_equal(a.rhs, b.rhs)

    ao, al, ar = _simple_bool_relation(a)
    bo, bl, br = _simple_bool_relation(b)
    if ao == "BOOLTRUE" and b.op == "TRUE": return _expr_equal(al, b.lhs)
    if bo == "BOOLTRUE" and a.op == "TRUE": return _expr_equal(bl, a.lhs)

    if ao == bo and _expr_equal(al, bl) and _expr_equal(ar, br): return True
    if ao == bo and ao in _SYMMETRIC_OPS and _expr_equal(al, br) and _expr_equal(ar, bl): return True
    if bo == _SWAP_OP.get(ao) and _expr_equal(al, br) and _expr_equal(ar, bl): return True
    return False


def expand_compound_array_assertion(a: NormalizedAssertion) -> List[NormalizedAssertion]:
    """Expand ARRAY({v0,...}, actual, N) into scalar equalities when explicit."""
    if a.op != "ARREQ": return [a]
    node = parse_c_expr(a.lhs)
    if not isinstance(node, c_ast.CompoundLiteral) or not isinstance(node.init, c_ast.InitList): return [a]
    vals = node.init.exprs or []
    n = _parse_int_literal(a.raw_args[2]) if len(a.raw_args) >= 3 else None
    if n is None or n < 0 or n > len(vals): return [a]
    actual = a.rhs
    # Only expand a simple expression base; this is exact C array element intent.
    return [NormalizedAssertion("EQ", c_ast_to_str(v), f"({actual})[{i}]", a.raw_macro, a.raw_args)
            for i, v in enumerate(vals[:n])]
