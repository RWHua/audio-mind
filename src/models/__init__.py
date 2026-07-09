"""Pydantic 数据模型：播客元数据、转写片段、洞察结果"""

from typing import Optional

from pydantic import BaseModel, Field


# ---- 播客元数据 ----
class PersonaData(BaseModel):
    """用户画像"""
    name: str = ""
    occupation: str = ""
    industry: str = ""
    education: str = ""
    professional_interests: list[str] = Field(default_factory=list)
    personal_interests: list[str] = Field(default_factory=list)
    short_term_goals: str = ""
    long_term_goals: str = ""
    style_preference: str = ""
    topic_keywords: list[str] = Field(default_factory=list)
    cognitive_bias: str = ""
    current_challenges: str = ""


class PodcastShow(BaseModel):
    """播客节目信息（来自 JSON-LD partOfSeries）"""
    name: str
    url: str = ""


class EpisodeMetadata(BaseModel):
    """单集播客元数据"""

    title: str                              # 单集标题
    podcast_name: str = ""                  # 播客名
    episode_number: str = ""                # 期号（如 E235）
    audio_url: str                          # 音频下载地址
    cover_url: str = ""                     # 封面图
    duration_seconds: Optional[int] = None  # 时长（秒）
    description: str = ""                   # 节目笔记
    source_url: str                         # 原始链接
    show: Optional[PodcastShow] = None      # 节目信息

    def short_topic(self, max_chars: int = 15) -> str:
        """从标题提取简短主题词（去掉期号）"""
        import re

        no_episode = re.sub(r"[Ee]\d+\s*", "", self.title).strip(" -，。-")
        if len(no_episode) <= max_chars:
            return no_episode
        # 按常见分隔符拆分，取第一个有意义的段
        parts = re.split(r"[，,：:\s\-—]", no_episode)
        result = ""
        for p in parts:
            if not p:
                continue
            if len(result + p) <= max_chars:
                result += p if not result else p
            else:
                break
        return result[:max_chars] if result else no_episode[:max_chars]


class TranscriptSegment(BaseModel):
    """带时间戳的转写片段"""

    start: float   # 起始秒数
    end: float     # 结束秒数
    text: str      # 转写文本


class TranscriptResult(BaseModel):
    """完整转写结果"""

    segments: list[TranscriptSegment] = Field(default_factory=list)
    full_text: str = ""        # 不带时间戳的纯文本
    language: str = "zh"
    duration: float = 0.0

    def token_estimate(self) -> int:
        """粗略 token 估算（中文约 1.5 字符/token）"""
        return int(len(self.full_text) / 1.5)


class InsightItem(BaseModel):
    """单条洞察"""
    title: str
    detail: str


class ActionItem(BaseModel):
    """行动项"""
    action: str
    reason: str
    difficulty: str = ""  # 低 / 中 / 高


class QuotationItem(BaseModel):
    """引述"""
    text: str
    context: str
    timestamp_approx: str = ""


class ControversialItem(BaseModel):
    """需批判看待的条目"""
    claim: str
    reason: str


class ResourceItem(BaseModel):
    """节目中提到的资源"""
    name: str
    type: str = ""         # 工具 / 书籍 / 文章 / 人物 / 其他
    description: str = ""


class AnalysisResult(BaseModel):
    """完整分析结果"""

    core_viewpoints: list[InsightItem] = Field(default_factory=list)
    personal_relevance: list[InsightItem] = Field(default_factory=list)
    action_items: list[ActionItem] = Field(default_factory=list)
    key_quotations: list[QuotationItem] = Field(default_factory=list)
    controversial_points: list[ControversialItem] = Field(default_factory=list)
    resources_mentioned: list[ResourceItem] = Field(default_factory=list)


class PipelineResult(BaseModel):
    """Pipeline 完整输出"""

    episode: EpisodeMetadata
    transcript: TranscriptResult
    analysis: Optional[AnalysisResult] = None
    output_dir: str = ""
    transcript_path: str = ""
    insights_path: str = ""
