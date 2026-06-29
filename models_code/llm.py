import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

# 加载项目根目录的 .env(密钥从那里读,不写死)
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

client = OpenAI(
    base_url="https://router.shengsuanyun.com/api/v1",
    api_key=os.environ["SHENGSUANYUN_API_KEY"],
)

try:
    completion = client.chat.completions.create(
        model="openai/gpt-5.4-nano",
        messages=[{"role": "user", "content": "Which number is larger, 9.11 or 9.8?"}],
        temperature=0.6,
        top_p=0.7,
        stream=True,
    )

    response_text = ""

    for chunk in completion:
        if chunk.choices and chunk.choices[0].delta.content is not None:
            content = chunk.choices[0].delta.content
            print(content, end="", flush=True)
            response_text += content

except Exception as e:
    print(f"Request failed: {e}")