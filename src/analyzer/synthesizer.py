"""分析合成模块：LLM 分析入口 + 分段 → 合成流程

协调整个分析过程：
1. 加载 prompt 模板 + 数据
2. 判断是否需要分段
3. 调用 LLM 进行分析
4. 解析 LLM 返回的 JSON
"""

import json
from typing import Optional

from src.analyzer.client import DeepSeekClient, load_prompt, extract_json
from src.analyzer.chunker import TextChunker
from src.exceptions import AnalysisError, SynthesisError
from src.models import AnalysisResult, InsightItem, ActionItem, QuotationItem, ControversialItem, ResourceItem, EpisodeMetadata
from src.utils.config import get_settings, AppSettings
from src.utils.logger import setup_logger

logger = setup_logger("audio-mind.analyzer.synthesizer")


def _parse_analysis_json(json_str: str) -> AnalysisResult:
    """将 LLM 返回的 JSON 字符串解析为 AnalysisResult

    Raises:
        AnalysisError: JSON 格式无效
    """
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        raise AnalysisError(
            "LLM 返回的 JSON 解析失败",
            detail=str(e),
        )

    return AnalysisResult(
        core_viewpoints=[InsightItem(**item) for item in data.get("core_viewpoints", [])],
        personal_relevance=[InsightItem(**item) for item in data.get("personal_relevance", [])],
        action_items=[ActionItem(**item) for item in data.get("action_items", [])],
        key_quotations=[QuotationItem(**item) for item in data.get("key_quotations", [])],
        controversial_points=[ControversialItem(**item) for item in data.get("controversial_points", [])],
        resources_mentioned=[ResourceItem(**item) for item in data.get("resources_mentioned", [])],
    )


def analyze_episode(
    transcript_text: str,
    persona_text: str,
    episode_info: str,
    settings: Optional[AppSettings] = None,
) -> AnalysisResult:
    """分析单集播客（入口函数）

    自动判断是否需要分段：
    - 文本较短 → 直接全文分析
    - 文本超长 → 分段摘要 → 全局合成

    Args:
        transcript_text: 转写全文
        persona_text: 用户画像文本（从 CLAUDE.md 提取）
        episode_info: 播客信息摘要（标题、播客名、时长、节目笔记等）
        settings: 应用配置

    Returns:
        结构化分析结果
    """
    if settings is None:
        settings = get_settings()

    chunker = TextChunker(settings)

    if chunker.should_chunk(transcript_text):
        logger.info("文本超长，使用分段分析流程")
        return _analyze_long(transcript_text, persona_text, episode_info, settings, chunker)
    else:
        logger.info("文本适中，使用直接分析流程")
        return _analyze_direct(transcript_text, persona_text, episode_info, settings)


def _analyze_direct(
    transcript_text: str,
    persona_text: str,
    episode_info: str,
    settings: AppSettings,
) -> AnalysisResult:
    """直接全文分析"""
    client = DeepSeekClient(settings)
    system_prompt, user_prompt = load_prompt("analyze")

    # 替换变量
    user_prompt = user_prompt.replace("{{persona}}", persona_text)
    user_prompt = user_prompt.replace("{{episode_info}}", episode_info)
    user_prompt = user_prompt.replace("{{transcript}}", transcript_text)

    logger.info("调用 LLM 进行全文分析...")
    response = client.chat(system_prompt, user_prompt)

    json_text = extract_json(response)
    logger.debug(f"LLM JSON 响应 (前200字符): {json_text[:200]}...")

    return _parse_analysis_json(json_text)


def _analyze_long(
    transcript_text: str,
    persona_text: str,
    episode_info: str,
    settings: AppSettings,
    chunker: TextChunker,
) -> AnalysisResult:
    """分段摘要 → 全局合成"""
    client = DeepSeekClient(settings)

    # --- 阶段 1: 分段摘要 ---
    chunks = chunker.chunk(transcript_text)
    logger.info(f"文本分为 {len(chunks)} 段，开始逐段摘要...")

    summary_parts: list[str] = []
    for i, chunk in enumerate(chunks, 1):
        sys_prompt, usr_prompt = load_prompt("summarize_chunk")
        usr_prompt = usr_prompt.replace("{{chunk_index}}", str(i))
        usr_prompt = usr_prompt.replace("{{total_chunks}}", str(len(chunks)))
        usr_prompt = usr_prompt.replace("{{chunk_text}}", chunk)

        logger.info(f"分析第 {i}/{len(chunks)} 段 ({len(chunk)} 字)...")
        response = client.chat(sys_prompt, usr_prompt)
        summary_parts.append(response)

    # --- 阶段 2: 全局合成 ---
    logger.info("开始全局合成...")
    chunk_summaries = "\n\n---\n\n".join(
        f"## 第 {i+1}/{len(summary_parts)} 段\n{s}"
        for i, s in enumerate(summary_parts)
    )

    sys_prompt, usr_prompt = load_prompt("synthesize")
    usr_prompt = usr_prompt.replace("{{persona}}", persona_text)
    usr_prompt = usr_prompt.replace("{{episode_info}}", episode_info)
    usr_prompt = usr_prompt.replace("{{chunk_summaries}}", chunk_summaries)

    response = client.chat(sys_prompt, usr_prompt)
    json_text = extract_json(response)

    return _parse_analysis_json(json_text)
