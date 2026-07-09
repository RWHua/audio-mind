"""文档生成模块：transcript.md 和 insights.md 的 Markdown 生成"""

from datetime import date
from pathlib import Path
from typing import Optional

from src.models import EpisodeMetadata, TranscriptResult, AnalysisResult
from src.utils.config import get_settings, AppSettings


class TranscriptGenerator:
    """转写文档生成器"""

    @staticmethod
    def generate(
        episode: EpisodeMetadata,
        transcript: TranscriptResult,
    ) -> str:
        """生成 transcript.md 的 Markdown 内容

        Args:
            episode: 播客元数据
            transcript: 转写结果

        Returns:
            Markdown 字符串
        """
        lines = [
            f"# {episode.podcast_name} {episode.episode_number} — {episode.title}",
            "",
            f"**播客**：{episode.podcast_name} | "
            f"**时长**：{_format_duration(episode.duration_seconds)} | "
            f"**来源**：[{episode.source_url[:50]}...]({episode.source_url})",
            "",
            "> 由 audio-mind Agent 自动转写 | " + date.today().isoformat(),
            "",
            "---",
            "",
            "## 完整转写",
            "",
        ]

        # 按时间戳排列（有时段时间戳则使用，否则使用全文）
        if transcript.segments:
            for seg in transcript.segments:
                timestamp = _format_timestamp(seg.start)
                lines.append(f"{timestamp} {seg.text}")
                lines.append("")
        else:
            lines.append(transcript.full_text)

        return "\n".join(lines)

    @staticmethod
    def save(
        content: str,
        output_dir: Path,
        filename: str = "transcript.md",
    ) -> Path:
        """保存转写文档到文件"""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        filepath = output_dir / filename
        filepath.write_text(content, encoding="utf-8")
        return filepath


class InsightsGenerator:
    """洞察文档生成器"""

    @staticmethod
    def generate(
        episode: EpisodeMetadata,
        analysis: AnalysisResult,
    ) -> str:
        """生成 insights.md 的 Markdown 内容

        Args:
            episode: 播客元数据
            analysis: 分析结果

        Returns:
            Markdown 字符串
        """
        lines = [
            f"# {episode.podcast_name} {episode.episode_number} — 个性化洞察",
            "",
            f"> 基于用户画像生成 | {date.today().isoformat()}",
            f"> 来源：[{episode.title}]({episode.source_url})",
            "",
            "---",
            "",
            "## 🎯 核心观点",
            "",
        ]
        for i, vp in enumerate(analysis.core_viewpoints, 1):
            lines.append(f"### {i}. {vp.title}")
            lines.append(f"{vp.detail}")
            lines.append("")

        lines.append("---")
        lines.append("")
        lines.append("## 🔗 与我的关联")
        lines.append("")
        for i, rel in enumerate(analysis.personal_relevance, 1):
            lines.append(f"### {i}. {rel.title}")
            lines.append(f"{rel.detail}")
            lines.append("")

        lines.append("---")
        lines.append("")
        lines.append("## ✅ 行动项")
        lines.append("")
        for i, act in enumerate(analysis.action_items, 1):
            diff_emoji = {"低": "🟢", "中": "🟡", "高": "🔴"}.get(act.difficulty, "")
            lines.append(f"### {i}. {act.action} {diff_emoji}")
            lines.append(f"**难度**: {act.difficulty}")
            lines.append(f"**理由**: {act.reason}")
            lines.append("")

        lines.append("---")
        lines.append("")
        lines.append("## 💬 关键引述")
        lines.append("")
        for i, quote in enumerate(analysis.key_quotations, 1):
            lines.append(f"### 引述 {i}")
            lines.append(f"> {quote.text}")
            lines.append("")
            lines.append(f"**上下文**: {quote.context}")
            if quote.timestamp_approx:
                lines.append(f"**时间**: {quote.timestamp_approx}")
            lines.append("")

        lines.append("---")
        lines.append("")
        lines.append("## ⚠️ 需批判看待")
        lines.append("")
        if analysis.controversial_points:
            for i, cp in enumerate(analysis.controversial_points, 1):
                lines.append(f"### {i}. {cp.claim}")
                lines.append(f"**质疑**: {cp.reason}")
                lines.append("")
        else:
            lines.append("> 本次未发现明显需批判的观点。")
            lines.append("")

        lines.append("---")
        lines.append("")
        lines.append("## 📚 节目中提到的资源")
        lines.append("")
        if analysis.resources_mentioned:
            for i, res in enumerate(analysis.resources_mentioned, 1):
                type_str = f"（{res.type}）" if res.type else ""
                lines.append(f"{i}. **{res.name}** {type_str}")
                if res.description:
                    lines.append(f"   {res.description}")
                lines.append("")
        else:
            lines.append("> 本次未提取到明确的可记录资源。")
            lines.append("")

        return "\n".join(lines)

    @staticmethod
    def save(
        content: str,
        output_dir: Path,
        filename: str = "insights.md",
    ) -> Path:
        """保存洞察文档到文件"""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        filepath = output_dir / filename
        filepath.write_text(content, encoding="utf-8")
        return filepath


# ============ 工具函数 ============

def _format_duration(seconds: Optional[int]) -> str:
    """秒数 → HH:MM:SS"""
    if seconds is None:
        return "未知"
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h > 0:
        return f"{h}时{m}分{s}秒"
    return f"{m}分{s}秒"


def _format_timestamp(start_seconds: float) -> str:
    """秒数 → [HH:MM:SS]"""
    h = int(start_seconds // 3600)
    m = int((start_seconds % 3600) // 60)
    s = int(start_seconds % 60)
    return f"[{h:02d}:{m:02d}:{s:02d}]"
