"""画像管理模块：从本地 persona.local.md（优先）或 CLAUDE.md 读取/写入用户画像"""

import re
from pathlib import Path
from typing import Optional

from src.models import PersonaData
from src.utils.logger import setup_logger

logger = setup_logger("audio-mind.persona")

PERSONA_HEADER = "## User Persona"
LOCAL_PERSONA_FILE = "persona.local.md"  # 本地画像文件（已被 .gitignore 排除，不提交到仓库）


class PersonaManager:
    """用户画像管理器

    负责读取用户画像，以及将填写好的画像写入。
    画像优先存储在本地 persona.local.md（不入 Git），
    兼容从 CLAUDE.md 的 ``## User Persona`` 段读取旧数据。
    画像存储格式见 DESIGN.md 5.1 节。
    """

    def __init__(self, project_root: Optional[Path] = None):
        if project_root is None:
            # 默认查找项目根目录（src/utils/persona.py → 项目根）
            project_root = Path(__file__).parent.parent.parent
        self.project_root = Path(project_root)
        self.claude_md_path = self.project_root / "CLAUDE.md"
        self.local_persona_path = self.project_root / LOCAL_PERSONA_FILE

    def has_persona(self) -> bool:
        """检查是否已有用户画像（本地文件或 CLAUDE.md 段）

        本地 persona.local.md 存在即视为有画像；
        否则检查 CLAUDE.md 中真正的 Markdown 二级标题行（排除代码块内引用）。
        """
        if self.local_persona_path.exists():
            return True
        if not self.claude_md_path.exists():
            return False
        content = self.claude_md_path.read_text(encoding="utf-8")
        # 匹配行首的 ## User Persona（Markdown 标题），排除代码块内的引用
        return bool(re.search(rf"^{re.escape(PERSONA_HEADER)}\s*$", content, re.MULTILINE))

    def read_persona(self) -> Optional[PersonaData]:
        """读取用户画像（本地文件优先，其次 CLAUDE.md 段）

        Returns:
            PersonaData（如果画像存在），否则 None
        """
        if not self.has_persona():
            logger.info("未找到用户画像")
            return None

        if self.local_persona_path.exists():
            persona_text = self.local_persona_path.read_text(encoding="utf-8")
        else:
            content = self.claude_md_path.read_text(encoding="utf-8")
            persona_text = self._extract_persona_section(content)

        if not persona_text:
            return None

        persona = self._parse_persona_text(persona_text)
        logger.info(f"用户画像已加载: {persona.name or '(匿名)'}")
        return persona

    def write_persona(self, persona: PersonaData) -> None:
        """将用户画像写入本地 persona.local.md（不写入 CLAUDE.md）"""
        persona_block = self._format_persona(persona)
        self.local_persona_path.write_text(persona_block, encoding="utf-8")
        logger.info(f"用户画像已写入: {self.local_persona_path}")

    def delete_persona(self) -> bool:
        """删除用户画像（本地文件；并兼容清理 CLAUDE.md 中的旧画像段）

        Returns:
            True 如果找到并删除，False 如果没有画像
        """
        removed = False

        if self.local_persona_path.exists():
            self.local_persona_path.unlink()
            removed = True

        if self.claude_md_path.exists():
            content = self.claude_md_path.read_text(encoding="utf-8")
            if PERSONA_HEADER in content:
                pattern = rf"\n*{re.escape(PERSONA_HEADER)}[\s\S]*?(?=\n##\s|\Z)"
                content = re.sub(pattern, "", content)
                self.claude_md_path.write_text(content.rstrip() + "\n", encoding="utf-8")
                removed = True

        if removed:
            logger.info("用户画像已删除")
        return removed

    def get_persona_text(self) -> str:
        """获取画像的纯文本表示（用于注入 prompt）

        Returns:
            画像文本（如果画像存在），否则空字符串
        """
        persona = self.read_persona()
        if persona is None:
            return ""

        lines = []
        if persona.name:
            lines.append(f"姓名: {persona.name}")
        if persona.occupation:
            lines.append(f"职业: {persona.occupation}")
        if persona.industry:
            lines.append(f"行业: {persona.industry}")
        if persona.education:
            lines.append(f"教育: {persona.education}")
        if persona.professional_interests:
            lines.append(f"专业兴趣: {', '.join(persona.professional_interests)}")
        if persona.personal_interests:
            lines.append(f"个人兴趣: {', '.join(persona.personal_interests)}")
        if persona.short_term_goals:
            lines.append(f"短期目标: {persona.short_term_goals}")
        if persona.long_term_goals:
            lines.append(f"长期目标: {persona.long_term_goals}")
        if persona.style_preference:
            lines.append(f"风格偏好: {persona.style_preference}")
        if persona.topic_keywords:
            lines.append(f"关注主题: {', '.join(persona.topic_keywords)}")
        if persona.cognitive_bias:
            lines.append(f"认知倾向: {persona.cognitive_bias}")
        if persona.current_challenges:
            lines.append(f"当前挑战: {persona.current_challenges}")

        return "\n".join(lines)

    # ============ 私有方法 ============

    @staticmethod
    def _extract_persona_section(content: str) -> Optional[str]:
        """提取 ## User Persona 到下一个 ## 标题之间的内容

        只匹配行首的 ## User Persona 标题，排除代码块内或行中的字符串引用。
        """
        pattern = rf"^{re.escape(PERSONA_HEADER)}\s*$[\s\S]*?(?=\n##\s|\Z)"
        match = re.search(pattern, content, re.MULTILINE)
        return match.group(0) if match else None

    @staticmethod
    def _parse_persona_text(text: str) -> PersonaData:
        """解析画像文本为 PersonaData 对象"""
        data: dict = {
            "name": "",
            "occupation": "",
            "industry": "",
            "education": "",
            "professional_interests": [],
            "personal_interests": [],
            "short_term_goals": "",
            "long_term_goals": "",
            "style_preference": "",
            "topic_keywords": [],
            "cognitive_bias": "",
            "current_challenges": "",
        }

        # 按 "**key**: value" 格式解析
        field_map = {
            "name": "name",
            "occupation": "occupation",
            "industry": "industry",
            "education": "education",
            "短期": "short_term_goals",
            "长期": "long_term_goals",
            "风格": "style_preference",
            "关注主题词": "_topic_keywords",
            "倾向": "cognitive_bias",
            "当前挑战": "current_challenges",
        }

        # 专业兴趣列表（以 - 开头）
        pro_section = re.search(r"### 专业兴趣\n([\s\S]*?)(?=###|\Z)", text)
        if pro_section:
            interests = re.findall(r"-\s*(.+)", pro_section.group(1))
            data["professional_interests"] = [i.strip() for i in interests]

        # 非专业兴趣列表
        per_section = re.search(r"### 非专业兴趣\n([\s\S]*?)(?=###|\Z)", text)
        if per_section:
            interests = re.findall(r"-\s*(.+)", per_section.group(1))
            data["personal_interests"] = [i.strip() for i in interests]

        # 当前挑战（支持 ### 标题下的列表 或 **当前挑战**: 单行值）
        challenges_section = re.search(r"### 当前挑战\n([\s\S]*?)(?=###|\Z)", text)
        if challenges_section:
            challenges = re.findall(r"-\s*(.+)", challenges_section.group(1))
            if challenges:
                data["current_challenges"] = "; ".join(c.strip() for c in challenges)

        # 字段键值对（支持 `**key**: value` 和 `- **key**: value` 两种格式）
        for line in text.split("\n"):
            line = line.strip()
            # strip leading list markers: "- " or "* "
            line_stripped = re.sub(r"^[-*]\s+", "", line)
            match = re.match(r"\*\*(.+?)\*\*[:：]\s*(.+)", line_stripped)
            if match:
                key_raw = match.group(1).strip()
                value = match.group(2).strip()
                # 尝试精确匹配 → 模糊匹配（如 "短期（6-12个月）" 匹配 "短期"）
                mapped = field_map.get(key_raw)
                if mapped is None:
                    for fk, fm in field_map.items():
                        if key_raw.startswith(fk):
                            mapped = fm
                            break
                if mapped == "_topic_keywords":
                    data["topic_keywords"] = [k.strip() for k in value.split(",")]
                elif mapped:
                    data[mapped] = value

        return PersonaData(**data)

    @staticmethod
    def _format_persona(persona: PersonaData) -> str:
        """格式化 PersonaData 为 Markdown"""
        lines = [
            PERSONA_HEADER,
            "<!--",
            "  由 audio-mind Agent 自动管理。",
            "  要修改画像，请直接编辑下方内容或删除本段后重新对话。",
            "  各字段说明见 DESIGN.md 第 5.1 节。",
            "-->",
            "",
            "### 基本信息",
            f"- **name**: {persona.name or '(未填写)'}",
            f"- **occupation**: {persona.occupation or '(未填写)'}",
            f"- **industry**: {persona.industry or '(未填写)'}",
            f"- **education**: {persona.education or '(未填写)'}",
            "",
            "### 专业兴趣",
        ]
        for interest in persona.professional_interests:
            lines.append(f"- {interest}")
        if not persona.professional_interests:
            lines.append("- (未填写)")

        lines.append("")
        lines.append("### 非专业兴趣")
        for interest in persona.personal_interests:
            lines.append(f"- {interest}")
        if not persona.personal_interests:
            lines.append("- (未填写)")

        lines.append("")
        lines.append("### 目标")
        lines.append(f"- **短期（6-12个月）**: {persona.short_term_goals or '(未填写)'}")
        lines.append(f"- **长期（3-5年）**: {persona.long_term_goals or '(未填写)'}")

        lines.append("")
        lines.append("### 内容偏好")
        lines.append(f"- **风格**: {persona.style_preference or '(未填写)'}")
        topics = ", ".join(persona.topic_keywords) if persona.topic_keywords else "(未填写)"
        lines.append(f"- **关注主题词**: {topics}")
        lines.append(f"- **倾向**: {persona.cognitive_bias or '(未填写)'}")

        lines.append("")
        lines.append("### 当前挑战")
        lines.append(f"- {persona.current_challenges or '(未填写)'}")

        lines.append("<!-- 完 -->")
        return "\n".join(lines) + "\n"


# 引导问题列表
QUESTIONNAIRE = [
    ("你的名字（或昵称）？", "name"),
    ("你的职业是什么？从事这个领域多久了？", "occupation"),
    ("你目前所在的行业/领域？", "industry"),
    ("你的教育背景或专业方向？", "education"),
    (
        "你目前最关注的技术/专业领域有哪些？\n"
        "  例如：大语言模型、AI Agent、知识管理、产品设计、创业...",
        "professional_interests",
    ),
    (
        "除专业之外，你对哪些非技术领域感兴趣？\n"
        "  例如：认知科学、效率工具、投资理财、个人成长、哲学...",
        "personal_interests",
    ),
    ("你近期的目标是什么？（6个月-1年内想达成的事）", "short_term_goals"),
    ("你的长期目标是什么？（3-5年的愿景）", "long_term_goals"),
    (
        "你对内容有什么偏好？\n"
        "  - 喜欢什么风格？（深度技术 vs 轻松科普、理论 vs 实践、数据 vs 故事）\n"
        "  - 特别关注哪些主题词？（例如：AI Agent、知识管理、架构设计...）\n"
        "  - 有什么偏见/倾向？（例如：信任有数据支撑的观点、对纯营销内容反感）",
        "style_preference",
    ),
    (
        "你当前面临什么挑战/困惑？（Agent 会尤其关注播客中与此相关的内容）",
        "current_challenges",
    ),
]
