"""测试自定义异常类"""

import pytest
from src.exceptions import (
    AudioMindError,
    DownloadError,
    PageFetchError,
    AudioExtractError,
    AudioDownloadError,
    TranscriptionError,
    WhisperModelError,
    WhisperRuntimeError,
    AnalysisError,
    LLMAPIError,
    ConfigurationError,
    PersonaError,
)


class TestExceptions:
    """异常类测试"""

    def test_base_exception(self):
        """基类异常消息格式"""
        e = AudioMindError("测试错误")
        assert str(e) == "测试错误"

    def test_exception_with_detail(self):
        """异常携带详情"""
        e = PageFetchError("页面抓取失败", detail="HTTP 502")
        assert "页面抓取失败" in str(e)
        assert "HTTP 502" in str(e)

    def test_download_errors_hierarchy(self):
        """下载异常继承关系"""
        assert issubclass(PageFetchError, DownloadError)
        assert issubclass(AudioExtractError, DownloadError)
        assert issubclass(AudioDownloadError, DownloadError)
        assert issubclass(DownloadError, AudioMindError)

    def test_transcription_errors_hierarchy(self):
        """转写异常继承关系"""
        assert issubclass(WhisperModelError, TranscriptionError)
        assert issubclass(WhisperRuntimeError, TranscriptionError)
        assert issubclass(TranscriptionError, AudioMindError)

    def test_analysis_errors_hierarchy(self):
        """分析异常继承关系"""
        assert issubclass(LLMAPIError, AnalysisError)
        assert issubclass(AnalysisError, AudioMindError)

    def test_config_error(self):
        """配置错误"""
        e = ConfigurationError("缺少 API Key")
        assert "缺少 API Key" in str(e)

    def test_persona_error(self):
        """画像错误"""
        e = PersonaError("读取画像失败")
        assert "读取画像失败" in str(e)

    def test_catch_base(self):
        """所有异常都可被 AudioMindError 捕获"""
        errors = [
            PageFetchError("e"),
            WhisperRuntimeError("e"),
            LLMAPIError("e"),
            ConfigurationError("e"),
        ]
        for e in errors:
            assert isinstance(e, AudioMindError)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
