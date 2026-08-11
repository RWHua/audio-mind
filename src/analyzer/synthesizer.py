"""分析合成模块：LLM 分析入口 + 分段 → 合成流程

协调整个分析过程：
1. 加载 prompt 模板 + 数据
2. 判断是否需要分段
3. 调用 LLM 进行分析
4. 解析 LLM 返回的 JSON
"""

import json
import time
from typing import Optional

from pydantic import ValidationError

from src.analyzer.client import DeepSeekClient, load_prompt, extract_json
from src.analyzer.chunker import TextChunker
from src.exceptions import AnalysisError, SynthesisError
from src.models import AnalysisResult, InsightItem, ActionItem, QuotationItem, ControversialItem, ResourceItem, EpisodeMetadata
from src.utils.config import get_settings, AppSettings
from src.utils.logger import setup_logger

logger = setup_logger("audio-mind.analyzer.synthesizer")


def _parse_analysis_json(json_str: str) -> AnalysisResult:
    """将 LLM 返回的 JSON 字符串解析为 AnalysisResult

    对非法输入做兜底处理，统一转为 AnalysisError（不泄漏 TypeError/AttributeError）：
    - 非字符串输入（None 等）→ TypeError → AnalysisError
    - JSON 语法错误 → JSONDecodeError → AnalysisError
    - 顶层不是对象（数组/字符串/数字）→ AttributeError → AnalysisError
    - 字段类型不符（dict 当 list、元素非对象）→ TypeError/ValidationError → AnalysisError

    Raises:
        AnalysisError: JSON 格式无效
    """
    try:
        data = json.loads(json_str)
    except (json.JSONDecodeError, TypeError) as e:
        raise AnalysisError(
            "LLM 返回的 JSON 解析失败",
            detail=str(e),
        )

    try:
        return AnalysisResult(
            core_viewpoints=[InsightItem(**item) for item in data.get("core_viewpoints", [])],
            personal_relevance=[InsightItem(**item) for item in data.get("personal_relevance", [])],
            action_items=[ActionItem(**item) for item in data.get("action_items", [])],
            key_quotations=[QuotationItem(**item) for item in data.get("key_quotations", [])],
            controversial_points=[ControversialItem(**item) for item in data.get("controversial_points", [])],
            resources_mentioned=[ResourceItem(**item) for item in data.get("resources_mentioned", [])],
        )
    except (AttributeError, TypeError, ValidationError) as e:
        raise AnalysisError(
            "LLM 返回的 JSON 结构不符合预期",
            detail=str(e),
        )


# LLM 返回 JSON 的修复次数上限
MAX_JSON_REPAIRS = 2


def _parse_with_repair(json_text: str, client: DeepSeekClient, max_repairs: int = MAX_JSON_REPAIRS) -> AnalysisResult:
    """解析 LLM 返回的 JSON，失败时交给 LLM 修复重试

    覆盖两类失败：
    - JSON 语法错误（json.loads 失败 → AnalysisError）
    - 结构错误（字段缺失/类型不符 → pydantic ValidationError）

    Args:
        json_text: LLM 原始返回文本
        client: DeepSeek 客户端（用于修复调用）
        max_repairs: 最大修复次数（默认 2）

    Returns:
        解析成功的 AnalysisResult

    Raises:
        SynthesisError: 修复 max_repairs 次后仍无法解析
    """
    # 规范化输入：None/非字符串统一转字符串，避免 replace/parse 崩溃
    current = json_text if isinstance(json_text, str) else str(json_text)

    for attempt in range(max_repairs + 1):
        try:
            return _parse_analysis_json(current)
        except (AnalysisError, ValidationError) as e:
            if attempt >= max_repairs:
                raise SynthesisError(
                    f"LLM 返回的 JSON 在 {max_repairs} 次修复后仍解析失败",
                    detail=f"原始响应: {json_text[:500]}\n最后错误: {e}",
                )
            logger.warning(f"JSON 解析失败（第 {attempt + 1} 次），请求 LLM 修复...: {e}")

            sys_prompt, usr_prompt = load_prompt("fix_json")
            # 先替换 error_detail（系统生成），再替换 original_output（LLM 内容可能含
            # "{{...}}" 字面量，后替换可避免被二次污染）
            usr_prompt = usr_prompt.replace("{{error_detail}}", str(e))
            usr_prompt = usr_prompt.replace("{{original_output}}", current)

            current = client.chat(sys_prompt, usr_prompt)
            # 修复返回同样可能带 ```json 代码块，先提取再进入下一轮校验
            current = extract_json(current)
            logger.debug(f"LLM 修复返回 (前200字符): {current[:200]}...")

    # 理论不可达（循环内已 return/raise），防御性兜底
    raise SynthesisError("LLM 返回的 JSON 解析失败", detail=json_text[:500])


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

    return _parse_with_repair(json_text, client)


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
        seg_start = time.monotonic()
        sys_prompt, usr_prompt = load_prompt("summarize_chunk")
        usr_prompt = usr_prompt.replace("{{chunk_index}}", str(i))
        usr_prompt = usr_prompt.replace("{{total_chunks}}", str(len(chunks)))
        usr_prompt = usr_prompt.replace("{{chunk_text}}", chunk)

        logger.info(f"分析第 {i}/{len(chunks)} 段 ({len(chunk)} 字)...")
        response = client.chat(sys_prompt, usr_prompt)
        summary_parts.append(response)
        logger.info(f"第 {i}/{len(chunks)} 段摘要完成，耗时: {time.monotonic() - seg_start:.1f}s")

    # --- 阶段 2: 全局合成 ---
    logger.info("开始全局合成...")
    syn_start = time.monotonic()
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
    logger.info(f"全局合成完成，耗时: {time.monotonic() - syn_start:.1f}s")

    return _parse_with_repair(json_text, client)
