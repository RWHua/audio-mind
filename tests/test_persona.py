"""测试 PersonaManager：画像读写删查（本地 persona.local.md 优先，兼容 CLAUDE.md 旧段）"""

import pytest
from pathlib import Path

from src.models import PersonaData
from src.utils.persona import PersonaManager, LOCAL_PERSONA_FILE


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

    # ── has_persona ──

    def test_has_persona_false_for_empty_file(self, tmp_path):
        """CLAUDE.md 无画像且无本地文件 → False"""
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text("# 项目标题\n\n一些内容\n", encoding="utf-8")

        mgr = PersonaManager(project_root=tmp_path)
        assert mgr.has_persona() is False

    def test_has_persona_false_when_no_file(self, tmp_path):
        """没有任何文件 → False"""
        mgr = PersonaManager(project_root=tmp_path)
        assert mgr.has_persona() is False

    def test_has_persona_true_from_claude_md(self, tmp_path):
        """CLAUDE.md 中有 ## User Persona 标题（旧格式兼容）"""
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text(
            "# 项目标题\n\n## User Persona\n\n### 基本信息\n- **name**: 测试\n",
            encoding="utf-8",
        )

        mgr = PersonaManager(project_root=tmp_path)
        assert mgr.has_persona() is True

    def test_has_persona_true_from_local_file(self, tmp_path):
        """本地 persona.local.md 存在 → True"""
        local = tmp_path / LOCAL_PERSONA_FILE
        local.write_text(
            f"{PERSONA_HEADER}\n\n### 基本信息\n- **name**: 测试\n",
            encoding="utf-8",
        )

        mgr = PersonaManager(project_root=tmp_path)
        assert mgr.has_persona() is True

    def test_has_persona_ignores_code_block(self, tmp_path):
        """代码块中的 Persona 引用不被识别"""
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text(
            "# 项目\n\n```python\nPERSONA_HEADER = '## User Persona'\n```\n",
            encoding="utf-8",
        )

        mgr = PersonaManager(project_root=tmp_path)
        assert mgr.has_persona() is False

    # ── read_persona ──

    def test_read_persona_returns_none_when_missing(self, tmp_path):
        """无画像时 read_persona 返回 None"""
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text("# 项目\n\n无画像内容\n", encoding="utf-8")

        mgr = PersonaManager(project_root=tmp_path)
        assert mgr.read_persona() is None

    def test_read_persona_from_local_file_preferred(self, tmp_path):
        """本地文件优先于 CLAUDE.md 旧段"""
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text(
            "# 项目\n\n## User Persona\n\n### 基本信息\n- **name**: 旧名字\n",
            encoding="utf-8",
        )
        local = tmp_path / LOCAL_PERSONA_FILE
        local.write_text(
            f"{PERSONA_HEADER}\n\n### 基本信息\n- **name**: 新名字\n",
            encoding="utf-8",
        )

        mgr = PersonaManager(project_root=tmp_path)
        persona = mgr.read_persona()
        assert persona is not None
        assert persona.name == "新名字"

    def test_read_persona_from_claude_md_legacy(self, tmp_path):
        """无本地文件时从 CLAUDE.md 旧段读取"""
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text(
            "# 项目\n\n## User Persona\n\n### 基本信息\n- **name**: 旧名字\n",
            encoding="utf-8",
        )

        mgr = PersonaManager(project_root=tmp_path)
        persona = mgr.read_persona()
        assert persona is not None
        assert persona.name == "旧名字"

    # ── write_persona ──

    def test_write_persona_writes_local_file(self, tmp_path):
        """写入生成 persona.local.md，不创建 CLAUDE.md"""
        mgr = PersonaManager(project_root=tmp_path)
        mgr.write_persona(_make_persona_data())

        local = tmp_path / LOCAL_PERSONA_FILE
        assert local.exists()
        content = local.read_text(encoding="utf-8")
        assert PERSONA_HEADER in content
        assert "测试用户" in content
        assert not (tmp_path / "CLAUDE.md").exists()

    def test_write_overwrites_existing_local(self, tmp_path):
        """写入覆盖已有本地画像"""
        local = tmp_path / LOCAL_PERSONA_FILE
        local.write_text(
            f"{PERSONA_HEADER}\n\n### 基本信息\n- **name**: 旧名字\n",
            encoding="utf-8",
        )

        mgr = PersonaManager(project_root=tmp_path)
        new_persona = _make_persona_data()
        new_persona.name = "新名字"
        mgr.write_persona(new_persona)

        content = local.read_text(encoding="utf-8")
        assert "新名字" in content
        assert "旧名字" not in content

    def test_write_and_read_persona(self, tmp_path):
        """写画像 → 读画像 往返"""
        mgr = PersonaManager(project_root=tmp_path)
        mgr.write_persona(_make_persona_data())

        read_back = mgr.read_persona()
        assert read_back is not None
        assert read_back.name == "测试用户"
        assert read_back.occupation == "测试工程师"
        assert "AI" in read_back.professional_interests
        assert read_back.short_term_goals == "掌握 Agent 开发"

    # ── delete_persona ──

    def test_delete_persona_local(self, tmp_path):
        """删除本地画像文件"""
        local = tmp_path / LOCAL_PERSONA_FILE
        local.write_text(
            f"{PERSONA_HEADER}\n\n### 基本信息\n- **name**: 测试\n",
            encoding="utf-8",
        )

        mgr = PersonaManager(project_root=tmp_path)
        assert mgr.has_persona() is True

        result = mgr.delete_persona()
        assert result is True
        assert mgr.has_persona() is False
        assert not local.exists()

    def test_delete_persona_cleans_legacy_claude_md(self, tmp_path):
        """兼容：同时清理 CLAUDE.md 中的旧画像段"""
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text(
            "# 项目\n\n## User Persona\n\n### 基本信息\n- **name**: 测试\n\n## 其他章节\n",
            encoding="utf-8",
        )

        mgr = PersonaManager(project_root=tmp_path)
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
        assert mgr.delete_persona() is False

    # ── get_persona_text ──

    def test_get_persona_text(self, tmp_path):
        """get_persona_text 返回格式化的画像文本"""
        mgr = PersonaManager(project_root=tmp_path)
        mgr.write_persona(_make_persona_data())

        text = mgr.get_persona_text()
        assert "测试用户" in text
        assert "测试工程师" in text

    def test_get_persona_text_empty_when_missing(self, tmp_path):
        """无画像时 get_persona_text 返回空字符串"""
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text("# 项目\n", encoding="utf-8")

        mgr = PersonaManager(project_root=tmp_path)
        assert mgr.get_persona_text() == ""


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
