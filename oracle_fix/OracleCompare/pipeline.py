# -*- coding: utf-8 -*-
"""Oracle comparison pipeline: extraction -> normalization -> matching."""
import re
from dataclasses import asdict
from typing import Dict, List

from oracle_fix.OracleCompare.assertion_normalizer import (
    extract_assertion_calls, normalize, structurally_equal, canonical_expr,
    expand_compound_array_assertion, NormalizedAssertion,
)
from OracleCompareLLM.semantic_equivalence import check_equivalence

MATCH_LEVEL_EXACT = "完全一致"
MATCH_LEVEL_REF_SUBSET_OF_GEN = "答案是生成用例的子集"
MATCH_LEVEL_GEN_SUBSET_OF_REF = "生成用例是答案的子集"
MATCH_LEVEL_MISMATCH = "不匹配"


def _expand_len1_array(n: NormalizedAssertion) -> List[NormalizedAssertion]:
    """ARRAY(expected, actual, 1) is exactly expected[0] == actual[0]."""
    if n.op != "ARREQ" or len(n.raw_args) < 3:
        return [n]
    try:
        length = int(re.sub(r"[uUlL]+$", "", n.raw_args[2].strip()), 0)
    except Exception:
        return [n]
    if length != 1:
        return [n]
    return [NormalizedAssertion("EQ", f"({n.lhs})[0]", f"({n.rhs})[0]", n.raw_macro, n.raw_args)]


def extract_normalized_assertions(source: str):
    result = []
    for name, args in extract_assertion_calls(source):
        n = normalize(name, args)
        if n is None:
            continue
        expanded = expand_compound_array_assertion(n)
        if len(expanded) == 1 and expanded[0] is n:
            expanded = _expand_len1_array(n)
        result.extend(expanded)
    return result


def compare_single_pair(a, b, use_smt_fallback: bool = True) -> dict:
    if structurally_equal(a, b):
        return {"equivalent": True, "method": "structural", "a": asdict(a), "b": asdict(b)}
    if not use_smt_fallback:
        return {"equivalent": False, "method": "structural", "a": asdict(a), "b": asdict(b)}
    try:
        smt_result = check_equivalence(a, b)
    except (NotImplementedError, ValueError, KeyError, TypeError) as e:
        return {"equivalent": None, "method": "unsupported", "error": str(e), "a": asdict(a), "b": asdict(b)}
    return {
        "equivalent": smt_result["equivalent"], "method": "smt",
        "smt_status": smt_result["status"], "counterexample": smt_result.get("counterexample"),
        "a": asdict(a), "b": asdict(b),
    }


def determine_match_level(fp: int, fn: int) -> str:
    if fp == 0 and fn == 0: return MATCH_LEVEL_EXACT
    if fp == 0 and fn > 0: return MATCH_LEVEL_GEN_SUBSET_OF_REF
    if fp > 0 and fn == 0: return MATCH_LEVEL_REF_SUBSET_OF_GEN
    return MATCH_LEVEL_MISMATCH


def _eq_graph(assertions: List[NormalizedAssertion]):
    """Build equality closure for simple EQ assertions (used after 1:1 matching)."""
    parent = {}
    def find(x):
        parent.setdefault(x, x)
        if parent[x] != x: parent[x] = find(parent[x])
        return parent[x]
    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb: parent[rb] = ra
    for a in assertions:
        if a.op == "EQ":
            l, r = canonical_expr(a.lhs), canonical_expr(a.rhs)
            union(l, r)
    return parent, find


def _entailed_by(assertion: NormalizedAssertion, oracle: List[NormalizedAssertion]) -> bool:
    """Conservative local implication: equality transitivity only."""
    if assertion.op != "EQ":
        return False
    parent, find = _eq_graph(oracle)
    l, r = canonical_expr(assertion.lhs), canonical_expr(assertion.rhs)
    if l not in parent or r not in parent:
        return False
    return find(l) == find(r)


def match_assertion_sets(gen_assertions: List, ref_assertions: List, use_smt_fallback: bool = True) -> dict:
    n_gen, n_ref = len(gen_assertions), len(ref_assertions)
    matrix = {(gi, ri): compare_single_pair(gen_assertions[gi], ref_assertions[ri], use_smt_fallback=use_smt_fallback)
              for gi in range(n_gen) for ri in range(n_ref)}

    adj = {gi: [ri for ri in range(n_ref) if matrix[(gi, ri)]["equivalent"] is True]
           for gi in range(n_gen)}
    match_ref_to_gen: Dict[int, int] = {}
    def try_kuhn(gi: int, visited: set) -> bool:
        for ri in adj[gi]:
            if ri in visited: continue
            visited.add(ri)
            if ri not in match_ref_to_gen or try_kuhn(match_ref_to_gen[ri], visited):
                match_ref_to_gen[ri] = gi; return True
        return False
    for gi in range(n_gen): try_kuhn(gi, set())

    matched_gi = set(match_ref_to_gen.values())
    matched = [(gi, ri, matrix[(gi, ri)]) for ri, gi in match_ref_to_gen.items()]
    raw_unmatched_gen = [gi for gi in range(n_gen) if gi not in matched_gi]
    raw_unmatched_ref = [ri for ri in range(n_ref) if ri not in match_ref_to_gen]

    # A relation such as a==c may be implied by {a==7, c==7}; count it as
    # covered without pretending it has a one-to-one source assertion.
    unmatched_generated = [gi for gi in raw_unmatched_gen if not _entailed_by(gen_assertions[gi], ref_assertions)]
    unmatched_reference = [ri for ri in raw_unmatched_ref if not _entailed_by(ref_assertions[ri], gen_assertions)]

    # Only unresolved pairs involving still-unmatched assertions can affect the
    # classification.  Cross-pairs between assertions already settled by exact
    # matches no longer inflate the case-level uncertainty count.
    uncertain = []
    ug = set(unmatched_generated); ur = set(unmatched_reference)
    for (gi, ri), cr in matrix.items():
        if cr["equivalent"] is None and gi in ug and ri in ur:
            uncertain.append((gi, ri, cr))

    tp_for_precision = n_gen - len(unmatched_generated)
    tp_for_recall = n_ref - len(unmatched_reference)
    precision = tp_for_precision / n_gen if n_gen else (1.0 if n_ref == 0 else 0.0)
    recall = tp_for_recall / n_ref if n_ref else (1.0 if n_gen == 0 else 0.0)
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    match_level = determine_match_level(len(unmatched_generated), len(unmatched_reference))
    return {
        "matched": matched,
        "uncertain": uncertain,
        "unmatched_generated": unmatched_generated,
        "unmatched_reference": unmatched_reference,
        "precision": precision, "recall": recall, "f1": f1,
        "match_level": match_level,
        "exact_match": match_level == MATCH_LEVEL_EXACT,
    }


def strip_code_fence(text: str) -> str:
    if text is None: return ""
    # Preserve all fenced blocks instead of silently dropping everything after
    # the first one.  If no complete fence is present, keep the original text.
    blocks = re.findall(r"```(?:[A-Za-z0-9_+.-]+)?\s*\n?(.*?)```", text, re.DOTALL)
    return "\n".join(blocks) if blocks else text


def compare_oracle_texts(generated_text: str, reference_text: str, use_smt_fallback: bool = True) -> dict:
    gen_source = strip_code_fence(generated_text)
    ref_source = strip_code_fence(reference_text)
    gen_all = extract_normalized_assertions(gen_source)
    ref_all = extract_normalized_assertions(ref_source)

    # Unknown custom assertion helpers are recorded but excluded from the legacy
    # four-way set count.  This preserves backward-compatible statistics while
    # the new automatic_match_level field prevents callers from trusting a
    # decision that ignored unsupported assertions.
    unknown_gen = [a.raw_macro for a in gen_all if a.op == "UNKNOWN"]
    unknown_ref = [a.raw_macro for a in ref_all if a.op == "UNKNOWN"]
    gen_assertions = [a for a in gen_all if a.op != "UNKNOWN"]
    ref_assertions = [a for a in ref_all if a.op != "UNKNOWN"]

    result = match_assertion_sets(gen_assertions, ref_assertions, use_smt_fallback=use_smt_fallback)
    result["num_generated"] = len(gen_assertions)
    result["num_reference"] = len(ref_assertions)
    result["unknown_generated"] = unknown_gen
    result["unknown_reference"] = unknown_ref

    # Non-empty text with zero recognized assertions is not evidence of an empty
    # oracle.  It may contain project-specific expectation helpers.
    unparsed_gen = bool(gen_source.strip()) and not gen_all
    unparsed_ref = bool(ref_source.strip()) and not ref_all
    result["unparsed_generated"] = unparsed_gen
    result["unparsed_reference"] = unparsed_ref
    result["requires_review"] = bool(unknown_gen or unknown_ref or unparsed_gen or unparsed_ref or result.get("uncertain"))
    result["decision_status"] = "requires_review" if result["requires_review"] else "automatic"
    result["automatic_match_level"] = None if result["requires_review"] else result["match_level"]
    return result


def compare_oracle_files(llm_source: str, ground_truth_source: str) -> List[dict]:
    llm_assertions = extract_normalized_assertions(llm_source)
    gt_assertions = extract_normalized_assertions(ground_truth_source)
    n = max(len(llm_assertions), len(gt_assertions)); results=[]
    for i in range(n):
        if i >= len(llm_assertions): results.append({"equivalent":False,"method":"missing_in_llm","index":i,"gt":asdict(gt_assertions[i])}); continue
        if i >= len(gt_assertions): results.append({"equivalent":False,"method":"extra_in_llm","index":i,"llm":asdict(llm_assertions[i])}); continue
        x=compare_single_pair(llm_assertions[i],gt_assertions[i]); x["index"]=i; results.append(x)
    return results
