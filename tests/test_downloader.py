"""测试下载模块工具函数：parse_duration、_extract_episode_number、_make_safe_filename"""

import pytest

from src.downloader.xiaoyuzhou import (
    parse_duration,
    _extract_episode_number,
    _make_safe_filename,
)
from src.models import EpisodeMetadata


class TestParseDuration:
    """ISO 8601 时长解析测试"""

    def test_minutes_only(self):
        """PT82M → 4920 秒"""
        assert parse_duration("PT82M") == 82 * 60

    def test_hours_and_minutes(self):
        """PT1H30M → 5400 秒"""
        assert parse_duration("PT1H30M") == 5400

    def test_hours_minutes_seconds(self):
        """PT1H30M45S → 5445 秒"""
        assert parse_duration("PT1H30M45S") == 5445

    def test_seconds_only(self):
        """PT90S → 90 秒"""
        assert parse_duration("PT90S") == 90

    def test_empty_string(self):
        """空字符串 → None"""
        assert parse_duration("") is None

    def test_none_value(self):
        """None → None"""
        assert parse_duration(None) is None

    def test_invalid_format(self):
        """无效格式 → None"""
        assert parse_duration("not-a-duration") is None

    def test_zero_duration(self):
        """PT0S → 0 秒"""
        assert parse_duration("PT0S") == 0

    def test_hours_only(self):
        """PT2H → 7200 秒"""
        assert parse_duration("PT2H") == 7200

    def test_large_duration(self):
        """PT10H30M15S → 37815 秒"""
        assert parse_duration("PT10H30M15S") == 37815


class TestExtractEpisodeNumber:
    """期号提取测试"""

    def test_standard_format(self):
        """标准 E235 格式"""
        assert _extract_episode_number("E235 与其担心 AI 改变你") == "E235"

    def test_lowercase_e(self):
        """小写 e 格式"""
        assert _extract_episode_number("e102 测试播客") == "E102"

    def test_no_episode_number(self):
        """无期号 → 空字符串"""
        assert _extract_episode_number("没有期号的标题") == ""

    def test_episode_at_end(self):
        """期号在末尾"""
        assert _extract_episode_number("播客标题 E999") == "E999"

    def test_multi_digit(self):
        """多位数字期号"""
        assert _extract_episode_number("E1234 特别节目") == "E1234"

    def test_episode_in_middle(self):
        """期号在标题中间"""
        assert _extract_episode_number("Vol. E050 特别篇") == "E050"


class TestMakeSafeFilename:
    """安全文件名生成测试"""

    def test_basic_filename(self):
        """基本文件名生成"""
        episode = EpisodeMetadata(
            title="测试播客",
            podcast_name="知行小酒馆",
            episode_number="E235",
            audio_url="https://example.com/audio.m4a",
            source_url="https://xiaoyuzhoufm.com/episode/xxx",
        )
        filename = _make_safe_filename(episode)
        assert filename.startswith("E235_知行小酒馆")
        assert filename.endswith(".m4a")

    def test_filename_with_special_chars(self):
        """特殊字符被替换为下划线"""
        episode = EpisodeMetadata(
            title="测试",
            podcast_name="播客:名*字",
            episode_number="E001",
            audio_url="https://example.com/audio.mp3?token=abc",
            source_url="https://xiaoyuzhoufm.com/episode/xxx",
        )
        filename = _make_safe_filename(episode)
        assert ":" not in filename
        assert "*" not in filename
        assert "?" not in filename
        assert filename.endswith(".mp3")

    def test_filename_no_extension_in_url(self):
        """URL 无后缀 → 默认 .m4a"""
        episode = EpisodeMetadata(
            title="测试",
            podcast_name="播客",
            episode_number="E001",
            audio_url="https://example.com/stream",
            source_url="https://xiaoyuzhoufm.com/episode/xxx",
        )
        filename = _make_safe_filename(episode)
        assert filename.endswith(".m4a")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
