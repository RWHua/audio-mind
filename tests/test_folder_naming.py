"""测试文件夹命名逻辑"""

import pytest
from src.utils.folder_naming import generate_folder_name, _sanitize


class TestGenerateFolderName:
    """文件夹命名测试"""

    def test_basic(self):
        """基础命名"""
        name = generate_folder_name("知行小酒馆", "E235", "E235 与其担心 AI 改变你")
        assert "知行小酒馆" in name
        assert "E235" in name
        assert "AI" in name or "改变" in name

    def test_no_episode_number(self):
        """无期号"""
        name = generate_folder_name("播客名", "", "某期节目标题")
        assert "播客名" in name

    def test_no_podcast_name(self):
        """无播客名"""
        name = generate_folder_name("", "E1", "某期节目标题")
        assert "E1" in name

    def test_long_title(self):
        """标题超长截断"""
        name = generate_folder_name(
            "播客",
            "E1",
            "这是一个非常非常非常非常非常非常非常非常非常非常非常长的播客标题需要截断处理",
            max_topic_chars=5,
        )
        parts = name.split("_")
        topic_part = parts[-1] if len(parts) > 1 else name
        assert len(topic_part) <= 15  # 默认 15

    def test_all_empty(self):
        """全空"""
        name = generate_folder_name("", "", "")
        assert name == "未命名播客"

    def test_special_chars(self):
        """特殊字符清理"""
        name = generate_folder_name("播客:名", "E1", "标题<测试>")
        assert ":" not in name
        assert "<" not in name
        assert ">" not in name


class TestSanitize:
    """文件名清理测试"""

    def test_remove_illegal_chars(self):
        """移除非法字符"""
        assert _sanitize('test<file>:name"?"') == "test_file__name___"
        assert _sanitize("normal_name") == "normal_name"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
