# -*- coding: utf-8 -*-
"""Batch comparison entry point for oracle JSON files."""
import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

from oracle_fix.OracleCompare.pipeline import compare_oracle_texts


def find_json_files(root_dir: Path, output_file: Optional[Path] = None) -> List[Path]:
    """Recursively collect input JSON files while excluding the output itself."""
    output_resolved = output_file.resolve() if output_file else None
    files = []
    for p in root_dir.rglob("*.json"):
        try:
            if output_resolved is not None and p.resolve() == output_resolved:
                continue
        except OSError:
            pass
        files.append(p)
    return sorted(files)


def load_test_cases(json_path: Path) -> List[dict]:
    with open(json_path, "r", encoding="utf-8-sig") as f:
        data = json.load(f)
    if isinstance(data, dict):
        # Do not accidentally re-process a previous comparison output.
        if "summary" in data and "results" in data:
            raise ValueError("looks like a comparison output file, not an input case file")
        data = [data]
    if not isinstance(data, list):
        raise ValueError(f"{json_path} top-level JSON must be a list or a case object")
    return data


def process_json_file(json_path: Path, root_dir: Path) -> List[dict]:
    results = []
    try:
        cases = load_test_cases(json_path)
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError) as e:
        return [{"source_file": str(json_path.relative_to(root_dir)), "error": f"file parse failed: {e}"}]

    for idx, case in enumerate(cases):
        function_sig = case.get("function_sig", "")
        test_sig = case.get("test_sig", "")
        reference_oracle = case.get("reference_oracle", "") or ""
        generated_oracle = case.get("generated_oracle", "") or ""
        base = {
            "source_file": str(json_path.relative_to(root_dir)), "case_index": idx,
            "function_sig": function_sig, "test_sig": test_sig,
            "reference_oracle": reference_oracle, "generated_oracle": generated_oracle,
        }
        if not reference_oracle.strip() and not generated_oracle.strip():
            results.append({**base, "error": "reference_oracle and generated_oracle are both empty"})
            continue
        try:
            cmp_result = compare_oracle_texts(generated_oracle, reference_oracle)
        except Exception as e:
            results.append({**base, "error": f"comparison failed: {type(e).__name__}: {e}"})
            continue
        results.append({**base, **cmp_result})
    return results


def summarize(all_results: List[dict]) -> dict:
    from oracle_fix.OracleCompare.pipeline import (
        MATCH_LEVEL_EXACT, MATCH_LEVEL_REF_SUBSET_OF_GEN,
        MATCH_LEVEL_GEN_SUBSET_OF_REF, MATCH_LEVEL_MISMATCH,
    )
    valid = [r for r in all_results if "error" not in r]
    errored = [r for r in all_results if "error" in r]
    total = len(valid)
    levels = [MATCH_LEVEL_EXACT, MATCH_LEVEL_REF_SUBSET_OF_GEN,
              MATCH_LEVEL_GEN_SUBSET_OF_REF, MATCH_LEVEL_MISMATCH]
    counts = {x: 0 for x in levels}
    for r in valid: counts[r.get("match_level", MATCH_LEVEL_MISMATCH)] += 1
    return {
        "total_cases": len(all_results), "valid_cases": total, "error_cases": len(errored),
        "match_level_counts": counts,
        "match_level_rates": {k: (v / total if total else 0.0) for k, v in counts.items()},
        "cases_with_uncertain_pairs": sum(bool(r.get("uncertain")) for r in valid),
        "cases_requiring_review": sum(bool(r.get("requires_review")) for r in valid),
        "avg_precision": sum(r["precision"] for r in valid) / total if total else 0.0,
        "avg_recall": sum(r["recall"] for r in valid) / total if total else 0.0,
        "avg_f1": sum(r["f1"] for r in valid) / total if total else 0.0,
    }


def compare(input_dir, output_file, verbose=True):
    root_dir = Path(input_dir)
    output_path = Path(output_file)
    if not root_dir.is_dir():
        raise ValueError(f"invalid input directory: {root_dir}")
    json_files = find_json_files(root_dir, output_path)
    if not json_files:
        raise ValueError(f"no input JSON files under {root_dir}")

    all_results = []
    for jf in json_files:
        file_results = process_json_file(jf, root_dir)
        all_results.extend(file_results)
        if verbose:
            for r in file_results:
                if "error" in r:
                    print(f"[ERROR] {r['source_file']} #{r.get('case_index','?')}: {r['error']}")
                else:
                    print(f"[OK] {r['source_file']} :: {r['test_sig']} level={r['match_level']} "
                          f"precision={r['precision']:.2f} recall={r['recall']:.2f}")

    stats = summarize(all_results)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({"summary": stats, "results": all_results}, f, ensure_ascii=False, indent=2, default=str)
    return stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input_dir")
    ap.add_argument("--output", required=True)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    try:
        stats = compare(args.input_dir, args.output, verbose=not args.quiet)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr); return 2
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
