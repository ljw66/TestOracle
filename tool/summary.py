import csv
import json
from pathlib import Path

# ============================================================
# 配置
# ============================================================

# 实验总目录
# 目录结构：
#
# ROOT_DIR/
# ├── project1/
# │   └── results/
# │       ├── gpt-4o/
# │       │   ├── all/
# │       │   │   ├── result.json
# │       │   │   ├── result_error_llm.json
# │       │   │   └── result_uncertain_llm.json
# │       │   ├── no_doc/
# │       │   └── ...
# │       └── deepseek/
# └── project2/
#
ROOT_DIR = r"D:\Paper\TestOracle\expr\2"

# 输出 CSV
OUTPUT_CSV = Path(ROOT_DIR) / "experiment_statistics.csv"


# ============================================================
# JSON 读取
# ============================================================

def load_json(file_path):
    """
    读取 JSON 文件。

    使用 utf-8-sig，可以同时兼容普通 UTF-8 和带 BOM 的 UTF-8 文件。
    如果文件不存在或解析失败，返回 None。
    """
    file_path = Path(file_path)
    
    if not file_path.exists():
        print(f"[WARNING] 文件不存在: {file_path}")
        return None
    
    try:
        with open(file_path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception as e:
        print(f"[ERROR] JSON读取失败: {file_path}")
        print(f"        {e}")
        return None


# ============================================================
# result.json 解析
# ============================================================

def parse_result_json(file_path):
    """
    解析 result.json 中需要的统计信息。
    """
    
    data = load_json(file_path)
    
    result = {
        "total_cases": 0,
        "error_cases": 0,
        "cases_with_uncertain_pairs": 0,
        
        "exact": 0,
        "answer_subset": 0,
        "generated_subset": 0,
        "mismatch": 0,
    }
    
    if data is None:
        return result
    
    summary = data.get("summary", {})
    
    result["total_cases"] = summary.get("total_cases", 0)
    result["error_cases"] = summary.get("error_cases", 0)
    result["cases_with_uncertain_pairs"] = summary.get(
        "cases_with_uncertain_pairs", 0
    )
    
    counts = summary.get("match_level_counts", {})
    
    result["exact"] = counts.get("完全一致", 0)
    result["answer_subset"] = counts.get("答案是生成用例的子集", 0)
    result["generated_subset"] = counts.get("生成用例是答案的子集", 0)
    result["mismatch"] = counts.get("不匹配", 0)
    
    return result


# ============================================================
# LLM 比较结果解析
# ============================================================

def parse_llm_json(file_path):
    """
    解析：
        result_error_llm.json
        result_uncertain_llm.json

    JSON格式：

    "summary": {
        "llm_match_level_counts": {
            "精确匹配": 2,
            "r包含g": 1,
            "g包含r": 0,
            "不匹配": 2
        }
    }

    映射关系：

    精确匹配
        -> 完全一致

    r包含g
        reference 包含 generated
        generated 是 reference 的子集
        -> 生成用例是答案的子集

    g包含r
        generated 包含 reference
        reference 是 generated 的子集
        -> 答案是生成用例的子集
    """
    
    data = load_json(file_path)
    
    result = {
        "exact": 0,
        "r_contains_g": 0,
        "g_contains_r": 0,
        "mismatch": 0,
    }
    
    if data is None:
        return result
    
    summary = data.get("summary", {})
    counts = summary.get("llm_match_level_counts", {})
    
    result["exact"] = counts.get("精确匹配", 0)
    result["r_contains_g"] = counts.get("r包含g", 0)
    result["g_contains_r"] = counts.get("g包含r", 0)
    result["mismatch"] = counts.get("不匹配", 0)
    
    return result


# ============================================================
# 单个实验组统计
# ============================================================

def process_experiment(project_name, model_name, experiment_name, experiment_dir):
    """
    统计一个实验组。
    """
    
    result_file = experiment_dir / "result.json"
    error_file = experiment_dir / "result_error_llm.json"
    uncertain_file = experiment_dir / "result_uncertain_llm.json"
    
    main_result = parse_result_json(result_file)
    error_result = parse_llm_json(error_file)
    uncertain_result = parse_llm_json(uncertain_file)
    
    # --------------------------------------------------------
    # 最终四类结果
    # --------------------------------------------------------
    
    # 完全一致
    final_exact = (
            main_result["exact"]
            + error_result["exact"]
            + uncertain_result["exact"]
    )
    
    # 答案是生成用例的子集
    #
    # result.json:
    #   "答案是生成用例的子集"
    #
    # LLM:
    #   g包含r
    #
    final_answer_subset = (
            main_result["answer_subset"]
            + error_result["g_contains_r"]
            + uncertain_result["g_contains_r"]
    )
    
    # 生成用例是答案的子集
    #
    # result.json:
    #   "生成用例是答案的子集"
    #
    # LLM:
    #   r包含g
    #
    final_generated_subset = (
            main_result["generated_subset"]
            + error_result["r_contains_g"]
            + uncertain_result["r_contains_g"]
    )
    
    # 不匹配
    final_mismatch = (
            main_result["mismatch"]
            + error_result["mismatch"]
            + uncertain_result["mismatch"]
    )
    
    final_classified_cases = (
            final_exact
            + final_answer_subset
            + final_generated_subset
            + final_mismatch
    )
    
    # --------------------------------------------------------
    # 比例
    # --------------------------------------------------------
    
    if final_classified_cases > 0:
        exact_rate = final_exact / final_classified_cases
        answer_subset_rate = final_answer_subset / final_classified_cases
        generated_subset_rate = final_generated_subset / final_classified_cases
        mismatch_rate = final_mismatch / final_classified_cases
    else:
        exact_rate = 0
        answer_subset_rate = 0
        generated_subset_rate = 0
        mismatch_rate = 0
    
    return {
        # 基本信息
        "project": project_name,
        "model": model_name,
        "experiment": experiment_name,
        
        # result.json 基本统计
        "total_cases": main_result["total_cases"],
        "error_cases": main_result["error_cases"],
        "cases_with_uncertain_pairs":
            main_result["cases_with_uncertain_pairs"],
        
        # ----------------------------------------------------
        # result.json 原始匹配结果
        # ----------------------------------------------------
        "result_完全一致":
            main_result["exact"],
        
        "result_答案是生成用例的子集":
            main_result["answer_subset"],
        
        "result_生成用例是答案的子集":
            main_result["generated_subset"],
        
        "result_不匹配":
            main_result["mismatch"],
        
        # ----------------------------------------------------
        # error LLM 统计
        # ----------------------------------------------------
        "error_llm_精确匹配":
            error_result["exact"],
        
        "error_llm_r包含g":
            error_result["r_contains_g"],
        
        "error_llm_g包含r":
            error_result["g_contains_r"],
        
        "error_llm_不匹配":
            error_result["mismatch"],
        
        # ----------------------------------------------------
        # uncertain LLM 统计
        # ----------------------------------------------------
        "uncertain_llm_精确匹配":
            uncertain_result["exact"],
        
        "uncertain_llm_r包含g":
            uncertain_result["r_contains_g"],
        
        "uncertain_llm_g包含r":
            uncertain_result["g_contains_r"],
        
        "uncertain_llm_不匹配":
            uncertain_result["mismatch"],
        
        # ----------------------------------------------------
        # 最终合并统计
        # ----------------------------------------------------
        "最终_完全一致":
            final_exact,
        
        "最终_答案是生成用例的子集":
            final_answer_subset,
        
        "最终_生成用例是答案的子集":
            final_generated_subset,
        
        "最终_不匹配":
            final_mismatch,
        
        "最终_统计用例数":
            final_classified_cases,
        
        # ----------------------------------------------------
        # 最终比例
        # ----------------------------------------------------
        "最终_完全一致率":
            exact_rate,
        
        "最终_答案是生成用例的子集率":
            answer_subset_rate,
        
        "最终_生成用例是答案的子集率":
            generated_subset_rate,
        
        "最终_不匹配率":
            mismatch_rate,
    }


# ============================================================
# 遍历所有项目
# ============================================================

def collect_statistics(root_dir):
    """
    遍历目录：

        root/
            project/
                results/
                    model/
                        experiment/

    返回所有实验组的统计结果。
    """
    
    root_dir = Path(root_dir)
    
    all_results = []
    
    if not root_dir.exists():
        raise FileNotFoundError(f"根目录不存在: {root_dir}")
    
    # 项目
    for project_dir in sorted(root_dir.iterdir()):
        
        if not project_dir.is_dir():
            continue
        
        results_dir = project_dir / "results"
        
        if not results_dir.exists():
            continue
        
        project_name = project_dir.name
        
        print(f"\n项目: {project_name}")
        
        # 模型
        for model_dir in sorted(results_dir.iterdir()):
            
            if not model_dir.is_dir():
                continue
            
            model_name = model_dir.name
            
            print(f"  模型: {model_name}")
            
            # 实验组
            for experiment_dir in sorted(model_dir.iterdir()):
                
                if not experiment_dir.is_dir():
                    continue
                
                # 至少存在 result.json 才认为是实验目录
                result_json = experiment_dir / "result.json"
                
                if not result_json.exists():
                    continue
                
                experiment_name = experiment_dir.name
                
                print(f"    实验: {experiment_name}")
                
                stat = process_experiment(
                    project_name,
                    model_name,
                    experiment_name,
                    experiment_dir,
                )
                
                all_results.append(stat)
    
    return all_results


# ============================================================
# CSV 输出
# ============================================================

def save_csv(results, output_file):
    """
    保存详细统计结果，并在 CSV 最后增加每个“模型 + 实验组”的汇总结果。

    例如：
        gpt-4o + all
        gpt-4o + no_doc
        gpt-4o + no_inline
        ...
        deepseek + all
        deepseek + no_doc
        ...

    注意：
    1. total_cases 按项目统计，每个项目只计算一次；
    2. 其他计数字段按该实验组下所有项目求和；
    3. 比例字段根据汇总后的数据重新计算，而不是直接求和。
    """

    if not results:
        print("没有找到实验结果。")
        return

    output_file = Path(output_file)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = list(results[0].keys())

    # ========================================================
    # 不直接求和的字段
    # ========================================================

    info_fields = {
        "project",
        "model",
        "experiment",
    }

    rate_fields = {
        "最终_完全一致率",
        "最终_答案是生成用例的子集率",
        "最终_生成用例是答案的子集率",
        "最终_不匹配率",
    }

    # ========================================================
    # 按 model + experiment 分组
    # ========================================================

    groups = {}

    for row in results:

        model = row["model"]
        experiment = row["experiment"]

        key = (model, experiment)

        if key not in groups:
            groups[key] = []

        groups[key].append(row)

    summary_rows = []

    # ========================================================
    # 分别统计每组实验
    # ========================================================

    for (model, experiment), rows in sorted(groups.items()):

        summary = {
            "project": "TOTAL",
            "model": model,
            "experiment": experiment,
        }

        # ----------------------------------------------------
        # total_cases 特殊处理
        #
        # 同一个项目只统计一次，防止重复累计。
        # ----------------------------------------------------

        project_total_cases = {}

        for row in rows:

            project = row["project"]

            if project not in project_total_cases:
                project_total_cases[project] = row.get(
                    "total_cases", 0
                )

        summary["total_cases"] = sum(
            project_total_cases.values()
        )

        # ----------------------------------------------------
        # 其他计数字段正常求和
        # ----------------------------------------------------

        for field in fieldnames:

            if field in info_fields:
                continue

            if field == "total_cases":
                continue

            if field in rate_fields:
                continue

            total_value = 0

            for row in rows:
                value = row.get(field, 0)

                if isinstance(value, (int, float)):
                    total_value += value

            summary[field] = total_value

        # ----------------------------------------------------
        # 重新计算最终匹配比例
        # ----------------------------------------------------

        final_exact = summary.get(
            "最终_完全一致", 0
        )

        final_answer_subset = summary.get(
            "最终_答案是生成用例的子集", 0
        )

        final_generated_subset = summary.get(
            "最终_生成用例是答案的子集", 0
        )

        final_mismatch = summary.get(
            "最终_不匹配", 0
        )

        final_total = (
            final_exact
            + final_answer_subset
            + final_generated_subset
            + final_mismatch
        )

        # 如果你的返回结果中还有“最终_总和”
        if "最终_总和" in fieldnames:
            summary["最终_总和"] = final_total

        if final_total > 0:

            summary["最终_完全一致率"] = (
                final_exact / final_total
            )

            summary[
                "最终_答案是生成用例的子集率"
            ] = (
                final_answer_subset / final_total
            )

            summary[
                "最终_生成用例是答案的子集率"
            ] = (
                final_generated_subset / final_total
            )

            summary["最终_不匹配率"] = (
                final_mismatch / final_total
            )

        else:

            summary["最终_完全一致率"] = 0

            summary[
                "最终_答案是生成用例的子集率"
            ] = 0

            summary[
                "最终_生成用例是答案的子集率"
            ] = 0

            summary["最终_不匹配率"] = 0

        summary_rows.append(summary)
    
    def format_fields(row):
        """
        格式化 CSV 输出：
        1. 比例字段转换为百分比，并保留两位小数；
        2. 其他浮点数字段保留两位小数；
        3. 整数字段保持不变。
        """
        
        rate_fields = {
            "最终_完全一致率",
            "最终_答案是生成用例的子集率",
            "最终_生成用例是答案的子集率",
            "最终_不匹配率",
        }
        
        formatted = {}
        
        for key, value in row.items():
            
            # 比例转换成百分比
            if key in rate_fields and isinstance(value, (int, float)):
                formatted[key] = f"{value * 100:.2f}%"
            
            # 其他浮点数保留两位小数
            elif isinstance(value, float):
                formatted[key] = f"{value:.2f}"
            
            else:
                formatted[key] = value
        
        return formatted
    
    # ========================================================
    # 写 CSV
    # ========================================================
    
    with open(
            output_file,
            "w",
            newline="",
            encoding="utf-8-sig"
    ) as f:
        
        writer = csv.DictWriter(
            f,
            fieldnames=fieldnames
        )
        
        writer.writeheader()
        
        # 每个项目的详细结果
        writer.writerows(
            format_fields(row)
            for row in results
        )
        
        # 每个实验组的汇总结果
        writer.writerows(
            format_fields(row)
            for row in summary_rows
        )

    print(
        f"\n统计完成，共统计 {len(results)} 条详细实验结果。"
    )

    print(
        f"生成 {len(summary_rows)} 条实验组汇总结果。"
    )

    print(f"结果已保存到：{output_file}")


# ============================================================
# 主程序
# ============================================================

def main():
    results = collect_statistics(ROOT_DIR)
    
    save_csv(
        results,
        OUTPUT_CSV
    )


if __name__ == "__main__":
    main()
