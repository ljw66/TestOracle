import json
import time
from pathlib import Path

from LLM.model import MODEL_NAME
from LLM.model import client
from LLM.prompt import PROMPT_ALL
from LLM.prompt import PROMPT_NO_CODE
from LLM.prompt import PROMPT_NO_DOC
from LLM.prompt import PROMPT_NO_DOC_INLINE
from LLM.prompt import PROMPT_NO_INLINE
from LLM.prompt import PROMPT_ONLY_SIG


def call_llm(prompt, max_retries=5):
    """
    调用大模型接口。

    如果请求异常或模型未返回有效文本，则自动重试。

    :param prompt: 用户提示词
    :param max_retries: 最大尝试次数
    :return: 模型生成的文本；全部失败时返回 None
    """
    
    for attempt in range(1, max_retries + 1):
        try:
            response = client.chat.completions.create(
                model=MODEL_NAME,
                temperature=0.5,
                messages=[
                    {
                        "role": "system",
                        "content": "You are an expert unit testing engineer."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                extra_body={"thinking": {"type": "disabled"}},
            )
            
            # 检查响应是否合法
            if (
                    response
                    and response.choices
                    and response.choices[0].message
                    and response.choices[0].message.content
            ):
                content = response.choices[0].message.content.strip()
                
                if content:
                    return content
        except Exception as e:
            print(f"[Warning] LLM 第 {attempt}/{max_retries} 次请求异常: {e}")
        
        if attempt < max_retries:
            wait_time = attempt * 2
            print(f"[Retry] {wait_time} 秒后重试...")
            time.sleep(wait_time)
    
    print(f"[Error] LLM 连续 {max_retries} 次请求失败。")
    
    return None


def generate_oracle(function_doc, function_code, function_pure_code, function_sig, test_sig, prefix, type):
    prompt = ''
    match type:
        case 1:
            prompt = PROMPT_ALL.format(
                function_doc=function_doc,
                function_code=function_code,
                function_sig=function_sig,
                test_sig=test_sig,
                prefix=prefix
            )
        case 2:
            prompt = PROMPT_NO_DOC.format(
                function_code=function_code,
                function_sig=function_sig,
                test_sig=test_sig,
                prefix=prefix
            )
        case 3:
            prompt = PROMPT_NO_INLINE.format(
                function_doc=function_doc,
                function_pure_code=function_pure_code,
                function_sig=function_sig,
                test_sig=test_sig,
                prefix=prefix
            )
        case 4:
            prompt = PROMPT_NO_DOC_INLINE.format(
                function_pure_code=function_pure_code,
                function_sig=function_sig,
                test_sig=test_sig,
                prefix=prefix
            )
        case 5:
            prompt = PROMPT_NO_CODE.format(
                function_doc=function_doc,
                function_sig=function_sig,
                test_sig=test_sig,
                prefix=prefix
            )
        case 6:
            prompt = PROMPT_ONLY_SIG.format(
                function_sig=function_sig,
                test_sig=test_sig,
                prefix=prefix
            )
    
    response = call_llm(prompt)
    
    return response


def process_json(input_file, output_file, type):
    with open(input_file, "r", encoding="utf-8-sig") as f:
        data = json.load(f)
    
    function_doc = data["function_doc"]
    function_code = data["function_code"]
    function_pure_code = data["function_pure_code"]
    function_sig = data["function_sig"]
    results = []
    for test in data["tests"]:
        print(f"Generating oracle for {test['test_sig']}...")
        generated_oracle = generate_oracle(
            function_doc=function_doc,
            function_code=function_code,
            function_pure_code=function_pure_code,
            function_sig=function_sig,
            test_sig=test["test_sig"],
            prefix=test["prefix"],
            type=type
        )
        results.append({
            "function_sig": data["function_sig"],
            "test_sig": test["test_sig"],
            "prefix": test["prefix"],
            "reference_oracle": test["oracle"],
            "generated_oracle": generated_oracle
        })
    
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(
            results,
            f,
            indent=2,
            ensure_ascii=False
        )
    
    print(f"Saved to {output_file}")


def GenOracle(test_dir, result_file, type):
    Path(result_file).mkdir(exist_ok=True)
    
    for json_file in Path(test_dir).rglob("*.json"):
        relative_path = json_file.relative_to(test_dir)
        output_file = (
                Path(result_file)
                / relative_path.parent
                / f"{json_file.stem}_result.json"
        )
        output_file.parent.mkdir(
            parents=True,
            exist_ok=True
        )
        # 如果结果文件已经存在且不为空，则跳过
        if output_file.exists() and output_file.stat().st_size > 0:
            print(f"⊙ Skip: {output_file}")
            continue
        try:
            process_json(str(json_file), str(output_file), type)
            print(f"✓ {json_file}")
        except Exception as e:
            print(f"✗ {json_file}")
            print(e)
