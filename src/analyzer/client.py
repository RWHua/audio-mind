"""DeepSeek API 客户端：OpenAI 兼容接口封装

处理与 DeepSeek API 的通信，包括超时、重试。
"""

import json
import re
import time
from pathlib import Path
from typing import Optional

import yaml
from openai import OpenAI

from src.exceptions import LLMAPIError
from src.utils.config import get_settings, AppSettings
from src.utils.logger import setup_logger

logger = setup_logger("audio-mind.analyzer")


class DeepSeekClient:
    """DeepSeek API 客户端"""

    def __init__(self, settings: Optional[AppSettings] = None):
        if settings is None:
            settings = get_settings()

        cfg = settings.deepseek

        if not cfg.api_key:
            raise LLMAPIError(
                "DeepSeek API Key 未配置",
                detail="请在 .env 文件中设置 DEEPSEEK_API_KEY",
            )

        self.client = OpenAI(
            api_key=cfg.api_key,
            base_url=cfg.base_url,
            timeout=cfg.timeout,
        )
        self.model = cfg.model
        self.max_tokens = cfg.max_tokens
        self.temperature = cfg.temperature

    def chat(self, system_prompt: str, user_prompt: str) -> str:
        """发送对话请求

        Args:
            system_prompt: 系统提示词
            user_prompt: 用户提示词（含变量替换后的完整 prompt）

        Returns:
            LLM 响应文本

        Raises:
            LLMAPIError: API 调用失败
        """
        logger.info(f"调用 DeepSeek API ({self.model})...")

        call_start = time.monotonic()
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=self.max_tokens,
                temperature=self.temperature,
            )
        except Exception as e:
            raise LLMAPIError(
                "DeepSeek API 调用失败",
                detail=str(e),
            )

        content = response.choices[0].message.content or ""
        usage = response.usage

        logger.info(
            f"API 调用完成: "
            f"耗时={time.monotonic() - call_start:.1f}s, "
            f"input={usage.prompt_tokens} tok, "
            f"output={usage.completion_tokens} tok, "
            f"total={usage.total_tokens} tok"
        )

        return content


def load_prompt(name: str) -> tuple[str, str]:
    """从 prompts/ 目录加载 prompt 模板

    Args:
        name: prompt 文件名（不含 .yaml）

    Returns:
        (system_prompt, user_prompt)
    """
    root = Path(__file__).parent.parent.parent
    prompt_path = root / "prompts" / f"{name}.yaml"

    with open(prompt_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    return data.get("system", ""), data.get("user", "")


def extract_json(text: str) -> str:
    """从 LLM 响应中提取 JSON 内容

    处理 LLM 可能在 JSON 前后添加 markdown 代码块标记的情况。
    """
    # 尝试匹配 ```json ... ``` 或 ``` ... ```
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if match:
        return match.group(1).strip()

    # 尝试匹配裸 JSON（以 { 开头 } 结尾）
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return text[start:end + 1]

    return text.strip()
