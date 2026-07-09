"""转写模块导出

支持三种转写引擎:
- Whisper (本地): faster-whisper，离线可用，CPU 上较慢
- Volcengine (云端): 火山引擎豆包语音识别，速度快，需 API 凭证
- Alibaba (云端): 阿里云智能语音交互，中文识别好，需 AccessKey
"""

from src.transcriber.transcriber import preprocess_audio, transcribe
from src.transcriber.volcengine import transcribe_volcengine
from src.transcriber.alibaba import transcribe_alibaba

__all__ = ["preprocess_audio", "transcribe", "transcribe_volcengine", "transcribe_alibaba"]
