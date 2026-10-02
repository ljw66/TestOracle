import json
import time
from pathlib import Path

from openai import OpenAI
from LLM.model import CHECK_MODEL
from LLM.model import client

# ============================================================
# 配置
# ============================================================

# API_KEY = "sk-5b73a2f281894ab68c870eadf6ce4e96"
# BASE_URL = "https://api.deepseek.com"
# MODEL_NAME = "deepseek-v4-flash"

MAX_RETRIES = 3
RETRY_DELAY = 2

# ============================================================
# 初始化客户端
# ============================================================

# if not API_KEY:
#     raise ValueError(
#         "未检测到 OPENAI_API_KEY 环境变量，请先设置大模型 API Key。"
#     )

# client_kwargs = {
#     "api_key": API_KEY
# }

# if BASE_URL:
#     client_kwargs["base_url"] = BASE_URL

# client = OpenAI(**client_kwargs)

# ============================================================
# Prompt
# ============================================================

SYSTEM_PROMPT = """
你是一名精通 C 语言、嵌入式软件测试和单元测试 Oracle 分析的软件测试专家。

你的任务是判断 reference_oracle 和 generated_oracle 两组 C 语言测试预言
在语义上是否匹配。

请注意：
1. 不要仅根据字符串或语法形式判断。
2. 需要理解 C 语言表达式、测试断言宏以及逻辑条件的实际语义。
3. 不同测试框架中的断言宏，只要表达相同约束，可以认为语义相同。
4. 变量名、常量表示方式、类型转换、括号等非语义差异不应导致误判。
5. 一组 Oracle 可能包含多条断言。

匹配级别只能分为以下四类：

【精确匹配】
reference_oracle 和 generated_oracle 表达的断言在语义上完全等价。

【r包含g】
两组 Oracle 并非完全等价，但是 generated_oracle 的断言全都能够在 reference_oracle 中找到。

【g包含r】
两组 Oracle 并非完全等价，但是 reference_oracle 的断言全都能够在 generated_oracle 中找到。

【不匹配】
两组 Oracle 的关系既不满足精确匹配，也不存在包含关系。

请只返回以下 JSON 格式：
{
  "match_level": "精确匹配"
}

match_level 的值只能是：
"精确匹配"
"r包含g"
"g包含r"
"不匹配"

不要输出 Markdown，不要输出其他解释。
"""


# ============================================================
# 调用大模型
# ============================================================

def judge_oracle_match(reference_oracle: str,
                       generated_oracle: str) -> str:
    """
    调用大模型判断两个 Oracle 的语义匹配级别。

    返回值只能是：
        精确匹配
        包含匹配
        不匹配
    """
    
    user_prompt = f"""
请判断以下两组 C 语言测试 Oracle 的语义匹配关系。

====================
Reference Oracle
====================
{reference_oracle}

====================
Generated Oracle
====================
{generated_oracle}
"""
    
    valid_levels = {
        "精确匹配",
        "r包含g",
        "g包含r",
        "不匹配"
    }
    
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.chat.completions.create(
                model=CHECK_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": SYSTEM_PROMPT
                    },
                    {
                        "role": "user",
                        "content": user_prompt
                    }
                ],
                temperature=0,
                response_format={
                    "type": "json_object"
                },
                extra_body={"enable_thinking": False},
            )
            
            content = response.choices[0].message.content
            
            result = json.loads(content)
            
            match_level = result.get("match_level")
            
            if match_level not in valid_levels:
                raise ValueError(
                    f"模型返回了非法的 match_level: {match_level}"
                )
            
            return match_level
        
        except Exception as e:
            print(
                f"[警告] 第 {attempt}/{MAX_RETRIES} 次调用失败：{e}"
            )
            
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)
            
            else:
                raise RuntimeError(
                    "调用大模型判断 Oracle 失败"
                ) from e


# ============================================================
# JSON 文件处理
# ============================================================

def process_error_json(json_path: str):
    """
    读取 JSON 文件：

    1. 遍历 results；
    2. 找出需要 LLM 判断的 result；
    3. 提取 reference_oracle 和 generated_oracle；
    4. 调用 LLM 判断；
    5. 在对应 result 中新增 llm_match_level；
    6. 在 summary 中新增 llm_match_level_counts；
    7. 将结果写回原 JSON 文件。
    """
    
    input_path = Path(json_path)
    # 输出文件固定保存在原 JSON 所在目录
    output_path = input_path.parent / "result_error_llm.json"
    
    # --------------------------------------------------------
    # 1. 读取 JSON
    # --------------------------------------------------------
    
    with input_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    
    results = data.get(
        "results",
        []
    )
    
    # --------------------------------------------------------
    # 2. 初始化 LLM 匹配统计
    # --------------------------------------------------------
    
    llm_match_level_counts = {
        "精确匹配": 0,
        "r包含g": 0,
        "g包含r": 0,
        "不匹配": 0
    }
    
    llm_results = []
    
    # --------------------------------------------------------
    # 3. 遍历所有 result
    # --------------------------------------------------------
    
    for index, item in enumerate(results):
        # ====================================================
        # 判断是否需要 LLM 处理
        # ====================================================
        # 当前逻辑：
        # 只有 error 非空时才进行 LLM 判断。
        # 例如：
        # "error": "Unknown Macro"
        # 会进行判断。
        # 而：
        # "error": ""
        # 不会进行判断。
        # ====================================================
        
        if not item.get("error"):
            continue
        
        reference_oracle = item.get(
            "reference_oracle",
            ""
        )
        
        generated_oracle = item.get(
            "generated_oracle",
            ""
        )
        
        print("=" * 70)
        
        print(
            f"正在处理 Result #{index}"
        )
        
        print(f"source_file: "
              f"{item.get('source_file', '')}")
        
        print(
            f"case_index: "
            f"{item.get('case_index', index)}"
        )
        
        print(
            f"error: "
            f"{item.get('error', '')}"
        )
        
        # ----------------------------------------------------
        # 4. 调用 LLM 判断 Oracle
        # ----------------------------------------------------
        
        match_level = judge_oracle_match(
            reference_oracle,
            generated_oracle
        )
        
        print(
            f"LLM 判断结果: {match_level}"
        )
        
        # ----------------------------------------------------
        # 5. 将 LLM 判断结果写入当前 result
        # ----------------------------------------------------
        
        llm_result = {"source_file": item.get("source_file", ""),
                      "case_index": item.get("case_index", index),
                      "function_sig": item.get("function_sig", ""),
                      "test_sig": item.get("test_sig", ""),
                      "reference_oracle": reference_oracle,
                      "generated_oracle": generated_oracle,
                      "error": item.get("error", ""),
                      "llm_match_level": match_level
                      }
        llm_results.append(llm_result)
        
        # ----------------------------------------------------
        # 6. 更新统计
        # ----------------------------------------------------
        
        llm_match_level_counts[
            match_level
        ] += 1
    
    # --------------------------------------------------------
    # 7. 构造最终输出 JSON
    # --------------------------------------------------------
    output_data = {
        "summary": {
            "llm_match_level_counts": llm_match_level_counts
        },
        "results": llm_results}
    
    # --------------------------------------------------------
    # 8. 保存为新的 JSON 文件
    # --------------------------------------------------------
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(
            output_data,
            f,
            ensure_ascii=False,
            indent=2)
    
    # --------------------------------------------------------
    # 9. 输出统计结果
    # --------------------------------------------------------
    
    print("\n" + "=" * 70)
    print("LLM Oracle 匹配分析完成")
    print("=" * 70)
    
    print(
        f"参与 LLM 比较的 Case 数量: "
        f"{len(llm_results)}"
    )
    
    print(
        f"精确匹配: "
        f"{llm_match_level_counts['精确匹配']}"
    )
    
    print(
        f"r包含g: "
        f"{llm_match_level_counts['r包含g']}"
    )
    
    print(
        f"g包含r: "
        f"{llm_match_level_counts['g包含r']}"
    )
    
    print(
        f"不匹配: "
        f"{llm_match_level_counts['不匹配']}"
    )
    
    print(f"\n结果已保存至: {json_path}")


def process_uncertain_json(json_path: str):
    """
    读取原始 JSON 文件，对 results 中 uncertain 非空的 case
    使用 LLM 进行 Oracle 语义比较。

    输出文件：
        result_uncertain_llm.json

    输出内容仅包括：
    1. LLM 匹配级别统计；
    2. 实际参与比较的 uncertain case。
    """
    
    input_path = Path(json_path)
    
    # 输出文件与输入文件位于同一目录
    output_path = input_path.parent / "result_uncertain_llm.json"
    
    # --------------------------------------------------------
    # 1. 读取输入 JSON
    # --------------------------------------------------------
    
    with input_path.open(
            "r",
            encoding="utf-8"
    ) as f:
        data = json.load(f)
    
    results = data.get("results", [])
    
    # --------------------------------------------------------
    # 2. 初始化统计
    # --------------------------------------------------------
    
    llm_match_level_counts = {
        "精确匹配": 0,
        "r包含g": 0,
        "g包含r": 0,
        "不匹配": 0
    }
    
    llm_results = []
    
    # --------------------------------------------------------
    # 3. 遍历 results
    # --------------------------------------------------------
    
    for index, item in enumerate(results):
        
        uncertain = item.get("uncertain", [])
        
        # uncertain 不存在或为空列表则跳过
        if not uncertain:
            continue
        
        reference_oracle = item.get(
            "reference_oracle",
            ""
        )
        
        generated_oracle = item.get(
            "generated_oracle",
            ""
        )
        
        print("=" * 70)
        print(f"正在处理 uncertain Result #{index}")
        
        print(
            f"source_file: "
            f"{item.get('source_file', '')}"
        )
        
        print(
            f"case_index: "
            f"{item.get('case_index', index)}"
        )
        
        print(
            f"uncertain: {uncertain}"
        )
        
        # ----------------------------------------------------
        # 4. 调用已有的 LLM 比较函数
        # ----------------------------------------------------
        
        match_level = judge_oracle_match(
            reference_oracle,
            generated_oracle
        )
        
        print(
            f"LLM 判断结果: {match_level}"
        )
        
        # ----------------------------------------------------
        # 5. 保存当前比较结果
        # ----------------------------------------------------
        
        llm_result = {
            "source_file": item.get(
                "source_file",
                ""
            ),
            "case_index": item.get(
                "case_index",
                index
            ),
            "function_sig": item.get(
                "function_sig",
                ""
            ),
            "test_sig": item.get(
                "test_sig",
                ""
            ),
            "reference_oracle": reference_oracle,
            "generated_oracle": generated_oracle,
            "uncertain": uncertain,
            "llm_match_level": match_level
        }
        
        llm_results.append(
            llm_result
        )
        
        # ----------------------------------------------------
        # 6. 更新统计
        # ----------------------------------------------------
        
        llm_match_level_counts[
            match_level
        ] += 1
    
    # --------------------------------------------------------
    # 7. 构造输出 JSON
    # --------------------------------------------------------
    
    output_data = {
        "summary": {
            "llm_match_level_counts":
                llm_match_level_counts
        },
        "results": llm_results
    }
    
    # --------------------------------------------------------
    # 8. 保存
    # --------------------------------------------------------
    
    with output_path.open(
            "w",
            encoding="utf-8"
    ) as f:
        json.dump(
            output_data,
            f,
            ensure_ascii=False,
            indent=2
        )
    
    # --------------------------------------------------------
    # 9. 输出统计
    # --------------------------------------------------------
    
    print("\n" + "=" * 70)
    print("Uncertain Oracle LLM 匹配分析完成")
    print("=" * 70)
    
    print(
        f"参与 LLM 比较的 Case 数量: "
        f"{len(llm_results)}"
    )
    
    print(
        f"精确匹配: "
        f"{llm_match_level_counts['精确匹配']}"
    )
    
    print(
        f"r包含g: "
        f"{llm_match_level_counts['r包含g']}"
    )
    
    print(
        f"g包含r: "
        f"{llm_match_level_counts['g包含r']}"
    )
    
    print(
        f"不匹配: "
        f"{llm_match_level_counts['不匹配']}"
    )
    
    print(
        f"\n结果已保存至: {output_path}"
    )


# ============================================================
# Main
# ============================================================

def main():
    json_file = "D:\\Paper\\TestOracle\\expr\\2\\SPARCV8\\results\\gpt-4o\\no_doc\\result.json"
    
    process_error_json(json_file)


if __name__ == "__main__":
    main()
