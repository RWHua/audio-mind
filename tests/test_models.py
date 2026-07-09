"""测试 Pydantic 数据模型"""

import pytest
from src.models import (
    EpisodeMetadata,
    PodcastShow,
    TranscriptSegment,
    TranscriptResult,
    InsightItem,
    ActionItem,
    QuotationItem,
    ControversialItem,
    ResourceItem,
    AnalysisResult,
    PipelineResult,
)


class TestEpisodeMetadata:
    """播客元数据模型测试"""

    def test_basic_creation(self):
        """基础创建"""
        episode = EpisodeMetadata(
            title="E235 测试标题",
            audio_url="https://example.com/audio.m4a",
            source_url="https://xiaoyuzhoufm.com/episode/xxx",
        )
        assert episode.title == "E235 测试标题"
        assert episode.audio_url == "https://example.com/audio.m4a"
        assert episode.episode_number == ""  # 无 podcast_name 时需手动设置

    def test_podcast_show(self):
        """播客节目信息"""
        show = PodcastShow(name="知行小酒馆", url="https://example.com")
        assert show.name == "知行小酒馆"

    def test_short_topic_simple(self):
        """简短主题提取 - 简单标题"""
        episode = EpisodeMetadata(
            title="与其担心 AI 改变你，不如今天就用它做一件小事",
            audio_url="https://example.com/audio.m4a",
            source_url="https://xiaoyuzhoufm.com/episode/xxx",
        )
        topic = episode.short_topic(max_chars=5)
        assert len(topic) <= 5

    def test_short_topic_with_episode(self):
        """简短主题提取 - 含期号"""
        episode = EpisodeMetadata(
            title="E235 与其担心 AI 改变你",
            audio_url="https://example.com/audio.m4a",
            source_url="https://xiaoyuzhoufm.com/episode/xxx",
        )
        topic = episode.short_topic(max_chars=10)
        # 期号被去掉
        assert "E235" not in topic

    def test_short_topic_max_chars(self):
        """简短主题长度限制"""
        episode = EpisodeMetadata(
            title="这是一个非常非常非常长的播客标题需要截断",
            audio_url="https://example.com/audio.m4a",
            source_url="https://xiaoyuzhoufm.com/episode/xxx",
        )
        topic = episode.short_topic(max_chars=10)
        assert len(topic) <= 10


class TestTranscriptResult:
    """转写结果模型测试"""

    def test_empty_result(self):
        """空结果"""
        result = TranscriptResult()
        assert result.segments == []
        assert result.full_text == ""
        assert result.token_estimate() == 0

    def test_token_estimate(self):
        """Token 估算"""
        result = TranscriptResult(full_text="你好" * 750)  # ~1500 chars
        est = result.token_estimate()
        assert est > 0

    def test_segments(self):
        """分段数据"""
        seg = TranscriptSegment(start=0.0, end=5.2, text="测试文本")
        result = TranscriptResult(
            segments=[seg],
            full_text="测试文本",
        )
        assert len(result.segments) == 1
        assert result.segments[0].text == "测试文本"


class TestAnalysisResult:
    """分析结果模型测试"""

    def test_empty_result(self):
        """空分析结果"""
        result = AnalysisResult()
        assert result.core_viewpoints == []
        assert result.action_items == []

    def test_with_viewpoints(self):
        """含观点的分析结果"""
        result = AnalysisResult(
            core_viewpoints=[InsightItem(title="观点1", detail="详细内容")],
            action_items=[
                ActionItem(
                    action="尝试用 DeepSeek API 做文本分析",
                    reason="播客中提到了 API 的易用性",
                    difficulty="低",
                )
            ],
        )
        assert len(result.core_viewpoints) == 1
        assert result.action_items[0].difficulty == "低"


class TestPipelineResult:
    """Pipeline 结果模型测试"""

    def test_full_result(self):
        """完整 Pipeline 结果"""
        episode = EpisodeMetadata(
            title="测试播客",
            audio_url="https://example.com/audio.m4a",
            source_url="https://example.com/episode/1",
        )
        transcript = TranscriptResult(full_text="测试转写文本")
        analysis = AnalysisResult(
            core_viewpoints=[InsightItem(title="测试观点", detail="详情")]
        )
        result = PipelineResult(
            episode=episode,
            transcript=transcript,
            analysis=analysis,
            output_dir="/tmp/output",
            transcript_path="/tmp/output/transcript.md",
            insights_path="/tmp/output/insights.md",
        )
        assert result.episode.title == "测试播客"
        assert result.output_dir == "/tmp/output"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
