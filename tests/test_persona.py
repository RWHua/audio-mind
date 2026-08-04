"""测试 PersonaManager：画像读写删查"""

import pytest
from pathlib import Path

from src.models import PersonaData
from src.utils.persona import PersonaManager


PERSONA_HEADER = "## User Persona"


def _make_persona_data() -> PersonaData:
    """创建一个测试用 PersonaData"""
    return PersonaData(
        name="测试用户",
        occupation="测试工程师",
        industry="AI/Agent 开发",
        education="本科",
        professional_interests=["AI", "后端开发"],
        personal_interests=["播客", "投资"],
        short_term_goals="掌握 Agent 开发",
        long_term_goals="成为技术专家",
        style_preference="逻辑分析型",
        topic_keywords=["Agent", "AI"],
        cognitive_bias="偏好数据支撑",
        current_challenges="基础薄弱",
    )


class TestPersonaManager:
    """PersonaManager 单元测试"""

    def test_has_persona_false_for_empty_file(self, tmp_path):
        """空文件 → has_persona 返回 False"""
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text("# 项目标题\n\n一些内容\n", encoding="utf-8")

        mgr = PersonaManager(project_root=tmp_path)
        assert mgr.has_persona() is False

    def test_has_persona_false_when_no_file(self, tmp_path):
        """CLAUDE.md 不存在 → has_persona 返回 False"""
        mgr = PersonaManager(project_root=tmp_path)
        assert mgr.has_persona() is False

    def test_has_persona_true(self, tmp_path):
        """CLAUDE.md 中有 ## User Persona 标题"""
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text(
            "# 项目标题\n\n## User Persona\n\n### 基本信息\n- **name**: 测试\n",
            encoding="utf-8",
        )

        mgr = PersonaManager(project_root=tmp_path)
        assert mgr.has_persona() is True

    def test_has_persona_ignores_code_block(self, tmp_path):
        """代码块中的 Persona 引用不被识别"""
        claude_md = tmp_path / "CLAUDE.md"
        # 注意：行首没有 ## ，不是真正的标题
        claude_md.write_text(
            "# 项目\n\n```python\nPERSONA_HEADER = '## User Persona'\n```\n",
            encoding="utf-8",
        )

        mgr = PersonaManager(project_root=tmp_path)
        assert mgr.has_persona() is False

    def test_read_persona_returns_none_when_missing(self, tmp_path):
        """无画像时 read_persona 返回 None"""
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text("# 项目\n\n无画像内容\n", encoding="utf-8")

        mgr = PersonaManager(project_root=tmp_path)
        assert mgr.read_persona() is None

    def test_write_and_read_persona(self, tmp_path):
        """写画像 → 读画像 往返"""
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text("# 项目\n\n原始内容\n", encoding="utf-8")

        mgr = PersonaManager(project_root=tmp_path)
        persona = _make_persona_data()

        # 写入
        mgr.write_persona(persona)
        content = claude_md.read_text(encoding="utf-8")
        assert PERSONA_HEADER in content
        assert "测试用户" in content

        # 读取
        read_back = mgr.read_persona()
        assert read_back is not None
        assert read_back.name == "测试用户"
        assert read_back.occupation == "测试工程师"
        assert "AI" in read_back.professional_interests
        assert read_back.short_term_goals == "掌握 Agent 开发"

    def test_write_persona_to_new_file(self, tmp_path):
        """CLAUDE.md 不存在时创建并写入"""
        mgr = PersonaManager(project_root=tmp_path)
        persona = _make_persona_data()

        mgr.write_persona(persona)

        claude_md = tmp_path / "CLAUDE.md"
        assert claude_md.exists()
        content = claude_md.read_text(encoding="utf-8")
        assert PERSONA_HEADER in content

    def test_write_overwrites_existing_persona(self, tmp_path):
        """写入覆盖已有画像"""
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text(
            "# 项目\n\n## User Persona\n\n### 基本信息\n- **name**: 旧名字\n\n## 其他章节\n",
            encoding="utf-8",
        )

        mgr = PersonaManager(project_root=tmp_path)
        new_persona = _make_persona_data()
        new_persona.name = "新名字"

        mgr.write_persona(new_persona)
        content = claude_md.read_text(encoding="utf-8")
        assert "新名字" in content
        assert "旧名字" not in content
        # 其他章节应保留
        assert "## 其他章节" in content

    def test_delete_persona(self, tmp_path):
        """删除画像"""
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text(
            "# 项目\n\n## User Persona\n\n### 基本信息\n- **name**: 测试\n\n## 其他章节\n",
            encoding="utf-8",
        )

        mgr = PersonaManager(project_root=tmp_path)
        assert mgr.has_persona() is True

        result = mgr.delete_persona()
        assert result is True
        assert mgr.has_persona() is False

        content = claude_md.read_text(encoding="utf-8")
        assert "## User Persona" not in content
        assert "## 其他章节" in content

    def test_delete_persona_when_missing(self, tmp_path):
        """删除不存在的画像返回 False"""
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text("# 项目\n\n没有画像\n", encoding="utf-8")

        mgr = PersonaManager(project_root=tmp_path)
        result = mgr.delete_persona()
        assert result is False

    def test_get_persona_text(self, tmp_path):
        """get_persona_text 返回格式化的画像文本"""
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text("# 项目\n", encoding="utf-8")

        mgr = PersonaManager(project_root=tmp_path)
        persona = _make_persona_data()
        mgr.write_persona(persona)

        text = mgr.get_persona_text()
        assert "测试用户" in text
        assert "测试工程师" in text

    def test_get_persona_text_empty_when_missing(self, tmp_path):
        """无画像时 get_persona_text 返回空字符串"""
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text("# 项目\n", encoding="utf-8")

        mgr = PersonaManager(project_root=tmp_path)
        text = mgr.get_persona_text()
        assert text == ""


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
