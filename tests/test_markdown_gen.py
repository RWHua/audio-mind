"""测试 Markdown 文档生成"""

import tempfile
import pytest
from pathlib import Path

from src.models import (
    EpisodeMetadata,
    TranscriptResult,
    TranscriptSegment,
    AnalysisResult,
    InsightItem,
    ActionItem,
)
from src.utils.markdown_gen import TranscriptGenerator, InsightsGenerator


class TestTranscriptGenerator:
    """转写文档生成测试"""

    def test_generate_basic(self):
        """基础文档生成"""
        episode = EpisodeMetadata(
            title="E1 测试标题",
            podcast_name="测试播客",
            episode_number="E1",
            audio_url="https://example.com/audio.m4a",
            source_url="https://xiaoyuzhoufm.com/episode/xxx",
            duration_seconds=3661,  # 1小时1分1秒
        )
        transcript = TranscriptResult(
            segments=[
                TranscriptSegment(start=0.0, end=5.0, text="欢迎收听测试播客。"),
                TranscriptSegment(start=5.0, end=10.0, text="今天我们来讨论一个话题。"),
            ],
            full_text="欢迎收听测试播客。\n今天我们来讨论一个话题。",
        )

        md = TranscriptGenerator.generate(episode, transcript)
        assert "测试播客" in md
        assert "E1" in md
        assert "[00:00:00]" in md
        assert "[00:00:05]" in md
        assert "欢迎收听" in md

    def test_save(self):
        """保存到文件"""
        episode = EpisodeMetadata(
            title="测试",
            audio_url="https://example.com/audio.m4a",
            source_url="https://example.com/ep",
        )
        transcript = TranscriptResult(full_text="测试")

        with tempfile.TemporaryDirectory() as tmpdir:
            content = TranscriptGenerator.generate(episode, transcript)
            path = TranscriptGenerator.save(content, Path(tmpdir))
            assert path.exists()
            assert path.read_text(encoding="utf-8") == content


class TestInsightsGenerator:
    """洞察文档生成测试"""

    def test_generate_basic(self):
        """基础文档生成"""
        episode = EpisodeMetadata(
            title="E1 测试",
            podcast_name="测试播客",
            episode_number="E1",
            audio_url="https://example.com/audio.m4a",
            source_url="https://example.com/ep",
        )
        analysis = AnalysisResult(
            core_viewpoints=[InsightItem(title="核心观点1", detail="详细描述")],
            personal_relevance=[InsightItem(title="与你相关", detail="关联说明")],
            action_items=[
                ActionItem(
                    action="尝试用 AI 做文本分析",
                    reason="播客中提到",
                    difficulty="低",
                )
            ],
        )

        md = InsightsGenerator.generate(episode, analysis)
        assert "测试播客" in md
        assert "核心观点1" in md
        assert "与你相关" in md
        assert "低" in md or "🟢" in md
        assert "🎯" in md
        assert "✅" in md
        assert "💬" in md
        assert "⚠️" in md
        assert "📚" in md

    def test_empty_sections(self):
        """空段落处理"""
        episode = EpisodeMetadata(
            title="测试",
            audio_url="https://example.com/audio.m4a",
            source_url="https://example.com/ep",
        )
        analysis = AnalysisResult()

        md = InsightsGenerator.generate(episode, analysis)
        assert "测试" in md
        # 没有崩溃即可

    def test_save(self):
        """保存洞察到文件"""
        episode = EpisodeMetadata(
            title="测试",
            audio_url="https://example.com/audio.m4a",
            source_url="https://example.com/ep",
        )
        analysis = AnalysisResult()

        with tempfile.TemporaryDirectory() as tmpdir:
            content = InsightsGenerator.generate(episode, analysis)
            path = InsightsGenerator.save(content, Path(tmpdir))
            assert path.exists()
            assert path.read_text(encoding="utf-8") == content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
