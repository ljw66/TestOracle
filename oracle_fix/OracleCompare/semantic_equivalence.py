# -*- coding: utf-8 -*-
"""Conservative optional Z3 fallback for assertion semantic equivalence."""
from typing import Dict, Tuple
from pycparser import c_ast
from OracleCompareLLM.assertion_normalizer import NormalizedAssertion, parse_c_expr

try:
    import z3
except ImportError:  # allow structural-only validation without z3-solver installed
    z3 = None

class SymbolTable:
    def __init__(self):
        if z3 is None: raise NotImplementedError("z3-solver is not installed")
        self.vars: Dict[str, object] = {}
        self.funcs: Dict[Tuple[str, int], object] = {}
    def get_var(self, name):
        if name not in self.vars: self.vars[name] = z3.Int(name)
        return self.vars[name]
    def get_func(self, name, arity):
        key=(name,arity)
        if key not in self.funcs:
            self.funcs[key]=z3.Function(f"uf_{name}", *([z3.IntSort()]*arity), z3.IntSort())
        return self.funcs[key]

def as_bool(expr):
    if isinstance(expr, z3.BoolRef): return expr
    return expr != 0

def as_arith(expr):
    if isinstance(expr, z3.BoolRef): return z3.If(expr,1,0)
    return expr

def _promote(a,b):
    a_real = z3.is_real(a) if hasattr(a,"sort") else False
    b_real = z3.is_real(b) if hasattr(b,"sort") else False
    if a_real and not b_real: b=z3.ToReal(b)
    elif b_real and not a_real: a=z3.ToReal(a)
    return a,b

def ast_to_z3(node,sym):
    if isinstance(node,c_ast.Constant):
        if "int" in node.type or node.type in ("long","unsigned long"):
            s=node.value.rstrip("uUlL")
            if len(s)>1 and s.startswith("0") and not s.lower().startswith("0x"): v=int(s,8)
            else: v=int(s,0)
            return z3.IntVal(v)
        if node.type in ("float","double"):
            return z3.RealVal(node.value.rstrip("fFlL"))
        if node.type=="char":
            raw=node.value.strip("'")
            return z3.IntVal(ord(raw[0]) if raw else 0)
        raise NotImplementedError(f"unsupported constant type: {node.type}")
    if isinstance(node,c_ast.ID):
        if node.name=="true": return z3.IntVal(1)
        if node.name=="false": return z3.IntVal(0)
        return sym.get_var(node.name)
    if isinstance(node,c_ast.UnaryOp):
        if node.op=="-": return -as_arith(ast_to_z3(node.expr,sym))
        if node.op=="+": return as_arith(ast_to_z3(node.expr,sym))
        if node.op=="!": return z3.Not(as_bool(ast_to_z3(node.expr,sym)))
        # Side-effecting ++/-- and pointer/bitwise unary operators are unsafe here.
        raise NotImplementedError(f"unsupported unary operator: {node.op}")
    if isinstance(node,c_ast.BinaryOp):
        l=ast_to_z3(node.left,sym); r=ast_to_z3(node.right,sym)
        if node.op=="&&": return z3.And(as_bool(l),as_bool(r))
        if node.op=="||": return z3.Or(as_bool(l),as_bool(r))
        l,r=_promote(as_arith(l),as_arith(r))
        ops={"+":lambda:a_plus(l,r),"-":lambda:l-r,"*":lambda:l*r,"/":lambda:l/r,"%":lambda:l%r,
             "==":lambda:l==r,"!=":lambda:l!=r,"<":lambda:l<r,"<=":lambda:l<=r,">":lambda:l>r,">=":lambda:l>=r}
        if node.op not in ops: raise NotImplementedError(f"unsupported binary operator: {node.op}")
        return ops[node.op]()
    if isinstance(node,c_ast.ArrayRef):
        idx=as_arith(ast_to_z3(node.subscript,sym))
        name=_expr_name(node.name)
        return sym.get_func(f"arr_{name}",1)(idx)
    if isinstance(node,c_ast.StructRef):
        base=as_arith(ast_to_z3(node.name,sym))
        return sym.get_func(f"field_{node.field.name}",1)(base)
    if isinstance(node,c_ast.FuncCall):
        if not isinstance(node.name,c_ast.ID): raise NotImplementedError("complex function callee")
        vals=[as_arith(ast_to_z3(x,sym)) for x in (node.args.exprs if node.args else [])]
        return sym.get_func(node.name.name,len(vals))(*vals)
    if isinstance(node,c_ast.TernaryOp):
        return z3.If(as_bool(ast_to_z3(node.cond,sym)),as_arith(ast_to_z3(node.iftrue,sym)),as_arith(ast_to_z3(node.iffalse,sym)))
    if isinstance(node,c_ast.Cast):
        # Without source type information, treating arbitrary casts as value-preserving is unsound.
        raise NotImplementedError("casts require type-aware modeling")
    raise NotImplementedError(f"unsupported AST node: {type(node).__name__}")

def a_plus(a,b): return a+b

def _expr_name(node):
    if isinstance(node,c_ast.ID): return node.name
    if isinstance(node,c_ast.StructRef): return f"{_expr_name(node.name)}_{node.field.name}"
    if isinstance(node,c_ast.ArrayRef): return f"{_expr_name(node.name)}_idx"
    raise NotImplementedError("complex array base")

def assertion_to_z3_bool(a,sym):
    def parse(s):
        n=parse_c_expr(s)
        if n is None: raise ValueError(f"cannot parse expression: {s}")
        return ast_to_z3(n,sym)
    if a.op=="TRUE": return as_bool(parse(a.lhs))
    if a.op=="FALSE": return z3.Not(as_bool(parse(a.lhs)))
    if a.op=="NULL": return as_arith(parse(a.lhs))==0
    if a.op=="NOTNULL": return as_arith(parse(a.lhs))!=0
    if a.op in ("ARREQ","MEMEQ","EACHEQ","WITHIN","PASS","BITS_HIGH","PRED","UNKNOWN"):
        raise NotImplementedError(f"SMT modeling is intentionally disabled for {a.op}")
    l=as_arith(parse(a.lhs)); r=as_arith(parse(a.rhs))
    if a.op in ("STREQ","STRNE"):
        cmp=sym.get_func("strcmp",2)(l,r)
        return cmp==0 if a.op=="STREQ" else cmp!=0
    ops={"EQ":lambda:l==r,"NE":lambda:l!=r,"LT":lambda:l<r,"LE":lambda:l<=r,"GT":lambda:l>r,"GE":lambda:l>=r}
    if a.op not in ops: raise NotImplementedError(f"unsupported assertion op: {a.op}")
    return ops[a.op]()

def check_equivalence(a:NormalizedAssertion,b:NormalizedAssertion,timeout_ms:int=5000):
    if z3 is None: raise NotImplementedError("z3-solver is not installed")
    sym=SymbolTable(); ea=as_bool(assertion_to_z3_bool(a,sym)); eb=as_bool(assertion_to_z3_bool(b,sym))
    s=z3.Solver(); s.set("timeout",timeout_ms); s.add(z3.Xor(ea,eb)); result=s.check()
    if result==z3.unsat: return {"equivalent":True,"status":"unsat","counterexample":None}
    if result==z3.sat:
        m=s.model(); return {"equivalent":False,"status":"sat","counterexample":{str(d):m[d] for d in m.decls()}}
    return {"equivalent":None,"status":"unknown","counterexample":None}
