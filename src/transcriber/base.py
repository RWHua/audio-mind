"""转写 Provider 抽象接口

定义 TranscriberProvider Protocol，用于 Pipeline 中的 provider 注册表。
所有转写引擎（whisper/volcengine/alibaba）均实现此接口。
"""

from pathlib import Path
from typing import Optional, Protocol

from src.models import TranscriptResult
from src.utils.config import AppSettings


class TranscriberProvider(Protocol):
    """转写引擎统一接口

    所有转写函数应符合此签名。各引擎可接受额外关键字参数，
    Pipeline 通过注册表分发到对应实现。
    """

    def __call__(
        self,
        audio_path: Path,
        settings: AppSettings,
        public_url: Optional[str] = None,
        episode_info: str = "",
        progress_callback=None,
    ) -> TranscriptResult:
        ...
