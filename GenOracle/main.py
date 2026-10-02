import json
import sys
import traceback
from pathlib import Path

from GenOracle import GenOracle
from OracleCompareLLM.CompareWithLLM import process_error_json, process_uncertain_json
from oracle_fix import Compare

# ============================================================
# 实验配置
# ============================================================

BASE_DIR = Path(r"expr")

PROJECTS = [
    "project_name"
]

GEN_TYPES = {
    "all": 1,
    "no_doc": 2,
    "no_inline": 3,
    "no_doc_inline": 4,
    "no_code": 5,
    "only_sig": 6,
}

MODELS = [
    "ds-v4f",
    "qwen36plus",
    "glm51",
    "kimi26"
]


# ============================================================
# 单个实验
# ============================================================

def run_single_experiment(project_name, model_name, gen_name, gen_type):
    """
    运行一个：
        project × model × gen_type
    实验。
    """

    test_dir = BASE_DIR / project_name / "test"
    result_dir = (
        BASE_DIR
        / project_name
        / "results"
        / model_name
        / gen_name
    )

    result_dir.mkdir(parents=True, exist_ok=True)

    result_file = result_dir / "result.json"
    finish_file = result_dir / ".finished"

    # --------------------------------------------------------
    # 已完成则直接跳过
    # --------------------------------------------------------
    if finish_file.exists():
        print(
            f"[SKIP] {project_name} | {model_name} | {gen_name}"
        )
        return

    print("\n" + "=" * 80)
    print(
        f"[RUN] Project={project_name}, "
        f"Model={model_name}, "
        f"Config={gen_name} ({gen_type})"
    )
    print("=" * 80)

    try:
        # ====================================================
        # 2. 生成 Oracle
        # ====================================================
        GenOracle(
            str(test_dir),
            str(result_dir),
            gen_type
        )

        # ====================================================
        # 3. 语法比较
        # ====================================================
        stats = Compare.compare(
            str(result_dir),
            str(result_file)
        )

        print(
            json.dumps(
                stats,
                ensure_ascii=False,
                indent=2
            )
        )

        # ====================================================
        # 4. LLM 比较 error
        # ====================================================
        process_error_json(str(result_file))

        # ====================================================
        # 5. LLM 比较 uncertain
        # ====================================================
        process_uncertain_json(str(result_file))

        # ====================================================
        # 6. 写完成标记
        # ====================================================
        finish_file.touch()

        print(
            f"[DONE] {project_name} | "
            f"{model_name} | {gen_name}"
        )

    except Exception as e:
        print(
            f"\n[ERROR] {project_name} | "
            f"{model_name} | {gen_name}"
        )
        print(f"Reason: {e}", file=sys.stderr)

        traceback.print_exc()

        # 当前实验出错，不影响其他实验继续
        return


# ============================================================
# 模型配置
# ============================================================


# ============================================================
# 批量运行
# ============================================================

def run_all():
    total = (
        len(PROJECTS)
        * len(MODELS)
        * len(GEN_TYPES)
    )

    current = 0

    for project_name in PROJECTS:
        for model_name in MODELS:
            for gen_name, gen_type in GEN_TYPES.items():

                current += 1

                print(
                    f"\n[{current}/{total}] "
                    f"{project_name} / "
                    f"{model_name} / "
                    f"{gen_name}"
                )

                run_single_experiment(
                    project_name,
                    model_name,
                    gen_name,
                    gen_type
                )


if __name__ == "__main__":
    run_all()
