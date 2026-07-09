"""自定义异常类层次：所有模块异常继承自 AudioMindError"""


class AudioMindError(Exception):
    """audio-mind 异常基类"""

    def __init__(self, message: str, *, detail: str = ""):
        self.message = message
        self.detail = detail
        super().__init__(self.message)

    def __str__(self):
        if self.detail:
            return f"{self.message}\n  详情: {self.detail}"
        return self.message


# ---- 下载阶段 ----
class DownloadError(AudioMindError):
    """下载阶段异常基类"""


class PageFetchError(DownloadError):
    """页面抓取失败（网络错误、404等）"""


class AudioExtractError(DownloadError):
    """音频链接提取失败"""


class AudioDownloadError(DownloadError):
    """音频文件下载失败"""


# ---- 转写阶段 ----
class TranscriptionError(AudioMindError):
    """转写阶段异常基类"""


class AudioPreprocessError(TranscriptionError):
    """音频预处理失败（格式转换等）"""


class WhisperModelError(TranscriptionError):
    """Whisper 模型加载失败"""


class WhisperRuntimeError(TranscriptionError):
    """转写运行时错误"""


# ---- 分析阶段 ----
class AnalysisError(AudioMindError):
    """分析阶段异常基类"""


class LLMAPIError(AnalysisError):
    """LLM API 调用失败"""


class ChunkingError(AnalysisError):
    """文本分段错误"""


class SynthesisError(AnalysisError):
    """跨段合成错误"""


# ---- 配置与画像 ----
class ConfigurationError(AudioMindError):
    """配置错误（缺少 API Key 等）"""


class PipelineTimeoutError(AudioMindError):
    """Pipeline 整体超时"""


class PersonaError(AudioMindError):
    """画像读写错误"""
