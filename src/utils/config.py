"""配置加载模块：从 settings.yaml 和 .env 读取配置，Pydantic 校验"""

import os
from pathlib import Path
from typing import Optional

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field


class WhisperConfig(BaseModel):
    model: str = "medium"  # 与 config/settings.yaml 保持一致，CPU 友好
    language: str = "zh"
    device: str = "auto"
    compute_type: str = "auto"
    beam_size: int = 5
    vad_filter: bool = True
    vad_threshold: float = 0.5
    chunk_length: int = 30


class DeepSeekConfig(BaseModel):
    base_url: str = "https://api.deepseek.com"
    api_key: str = ""
    model: str = "deepseek-chat"
    max_tokens: int = 4096
    temperature: float = 0.7
    timeout: int = 120


class ChunkingConfig(BaseModel):
    token_threshold: int = 80000
    chunk_size: int = 8000
    overlap: float = 0.1


class OutputConfig(BaseModel):
    base_dir: str = "output"
    transcript_file: str = "transcript.md"
    insights_file: str = "insights.md"
    max_topic_chars: int = 15


class PipelineConfig(BaseModel):
    """Pipeline 级配置"""
    timeout: int = 7200  # 整体超时秒数（2 小时），0 = 不限
    warn_local_whisper_minutes: int = 30  # 音频超过此分钟数时对本地转写发出警告


class RetryConfig(BaseModel):
    max_attempts: int = 3
    backoff_min: float = 1.0
    backoff_max: float = 30.0
    backoff_factor: float = 2.0


class DownloadConfig(BaseModel):
    chunk_size: int = 8192
    timeout: int = 300
    temp_dir: str = "temp_audio"
    resume: bool = True  # 是否启用断点续传（Range 请求）


class VolcengineConfig(BaseModel):
    app_id: str = ""
    access_token: str = ""
    resource_id: str = "volc.bigasr.auc.flash"
    model_name: str = "bigmodel"
    chunk_duration: int = 1500       # 单段最长秒数（25分钟）
    api_timeout: int = 180           # 单段 API 超时秒数


class AlibabaConfig(BaseModel):
    access_key_id: str = ""
    access_key_secret: str = ""
    app_key: str = "nls-service-multi-domain"
    oss_bucket: str = "audio-mind-temp"
    oss_region: str = "cn-shanghai"
    max_wait: int = 600             # 最大轮询等待秒数（10 分钟）


class TranscriberConfig(BaseModel):
    provider: str = "whisper"        # "whisper" | "volcengine" | "alibaba"


class AppSettings(BaseModel):
    whisper: WhisperConfig = Field(default_factory=WhisperConfig)
    volcengine: VolcengineConfig = Field(default_factory=VolcengineConfig)
    alibaba: AlibabaConfig = Field(default_factory=AlibabaConfig)
    transcriber: TranscriberConfig = Field(default_factory=TranscriberConfig)
    deepseek: DeepSeekConfig = Field(default_factory=DeepSeekConfig)
    chunking: ChunkingConfig = Field(default_factory=ChunkingConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    pipeline: PipelineConfig = Field(default_factory=PipelineConfig)
    retry: RetryConfig = Field(default_factory=RetryConfig)
    download: DownloadConfig = Field(default_factory=DownloadConfig)


def _resolve_env(value: str) -> str:
    """解析 ${VAR:-default} 格式的环境变量引用"""
    import re

    pattern = r"\$\{(\w+)(?::-([^}]*))?\}"
    match = re.fullmatch(pattern, value.strip())
    if match:
        var_name = match.group(1)
        default = match.group(2)
        return os.environ.get(var_name, default if default is not None else "")
    return value


def _deep_resolve(data: dict) -> dict:
    """递归解析字典中的环境变量引用"""
    for key, value in data.items():
        if isinstance(value, str):
            data[key] = _resolve_env(value)
        elif isinstance(value, dict):
            _deep_resolve(value)
    return data


def get_settings(config_path: Optional[str] = None) -> AppSettings:
    """加载并校验配置"""
    # 加载 .env
    env_path = Path(__file__).parent.parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
    else:
        load_dotenv()

    # 加载 settings.yaml
    if config_path is None:
        config_path = Path(__file__).parent.parent.parent / "config" / "settings.yaml"
    else:
        config_path = Path(config_path)

    raw = {}
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

    raw = _deep_resolve(raw)

    # 从环境变量注入 API Key
    if "deepseek" not in raw:
        raw["deepseek"] = {}
    raw["deepseek"]["api_key"] = os.environ.get("DEEPSEEK_API_KEY", "")

    # --- 火山引擎 ASR 凭证注入 ---
    if "volcengine" not in raw:
        raw["volcengine"] = {}
    raw["volcengine"]["app_id"] = os.environ.get("VOLCENGINE_APP_ID", raw["volcengine"].get("app_id", ""))
    raw["volcengine"]["access_token"] = os.environ.get("VOLCENGINE_ACCESS_TOKEN", raw["volcengine"].get("access_token", ""))

    # --- 阿里云 ASR 凭证注入 ---
    if "alibaba" not in raw:
        raw["alibaba"] = {}
    raw["alibaba"]["access_key_id"] = os.environ.get("ALIBABA_ACCESS_KEY_ID", raw["alibaba"].get("access_key_id", ""))
    raw["alibaba"]["access_key_secret"] = os.environ.get("ALIBABA_ACCESS_KEY_SECRET", raw["alibaba"].get("access_key_secret", ""))

    return AppSettings(**raw)
