from openai import OpenAI

# ======================
# 模型配置
# ======================
client = OpenAI(
    base_url="",
    api_key="",
)

MODEL_NAME = "deepseek-v4-flash-0731"
# MODEL_NAME = "qwen3.6-plus"
# MODEL_NAME = "glm-5.1"
# MODEL_NAME = "kimi-k2.6"

CHECK_MODEL = "deepseek-v4-flash-0731"


def call_model(prompt):
    response = client.chat.completions.create(
        model=MODEL_NAME,
        temperature=0.5,
        messages=[
            {"role": "user", "content": prompt}
        ]
    )
    
    return response.choices[0].message.content.strip()
