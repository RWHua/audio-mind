"""核心 Pipeline：串联下载 → 转写 → 分析完整流程

入口函数:
- run_pipeline(url) → PipelineResult: 通过 Claude Code 对话中的 Bash 调用
- main(): CLI 入口（python -m src.pipeline --url <链接>）
"""

import sys
import time
import re
import os
from pathlib import Path
from typing import Optional

from src.exceptions import AudioMindError, ConfigurationError, PipelineTimeoutError
from src.models import PipelineResult, EpisodeMetadata, TranscriptResult, AnalysisResult
from src.utils.config import get_settings, AppSettings, TranscriberConfig
from src.utils.logger import setup_logger
from src.utils.persona import PersonaManager
from src.utils.folder_naming import generate_folder_name
from src.utils.markdown_gen import TranscriptGenerator, InsightsGenerator
from src.downloader import fetch_episode_metadata, download_audio
from src.transcriber import transcribe, transcribe_volcengine, transcribe_alibaba
from src.analyzer import analyze_episode

logger = setup_logger("audio-mind.pipeline")


def _build_episode_info(episode: EpisodeMetadata) -> str:
    """构建播客信息摘要字符串"""
    parts = [
        f"播客名称: {episode.podcast_name}",
        f"单集标题: {episode.title}",
    ]
    if episode.episode_number:
        parts.append(f"期号: {episode.episode_number}")
    if episode.duration_seconds:
        m = episode.duration_seconds // 60
        s = episode.duration_seconds % 60
        parts.append(f"时长: {m}分{s}秒")
    if episode.description:
        desc = episode.description
        if len(desc) > 1000:
            desc = desc[:1000] + "...(截断)"
        parts.append(f"\n节目笔记:\n{desc}")
    return "\n".join(parts)


def _check_timeout(start_time: float, settings: AppSettings, stage: str) -> None:
    """检查 Pipeline 是否超时

    Raises:
        PipelineTimeoutError: 超过配置的超时时间
    """
    if settings.pipeline.timeout <= 0:
        return
    elapsed = time.time() - start_time
    if elapsed > settings.pipeline.timeout:
        raise PipelineTimeoutError(
            f"Pipeline 执行超时（>{settings.pipeline.timeout}s），当前阶段: {stage}",
            detail=f"已耗时 {elapsed:.0f}s",
        )


def _warn_long_audio(duration_seconds: Optional[int], settings: AppSettings) -> None:
    """长音频 + 本地转写时发出耗时警告"""
    if (
        settings.transcriber.provider == "whisper"
        and duration_seconds
        and duration_seconds > settings.pipeline.warn_local_whisper_minutes * 60
    ):
        minutes = duration_seconds // 60
        est_hours_low = minutes * 3 / 60   # 3x 实时比
        est_hours_high = minutes * 6 / 60  # 6x 实时比
        logger.warning(
            f"⚠ 检测到长音频 ({minutes} 分钟) 使用本地 Whisper 转写。\n"
            f"   CPU 上预估耗时: {est_hours_low:.1f} ~ {est_hours_high:.1f} 小时。\n"
            f"   建议: 在 settings.yaml 中将 transcriber.provider 切换为 "
            f"'volcengine' 或 'alibaba' 以大幅加速。"
        )


def _ensure_persona(settings: AppSettings) -> str:
    """确保用户画像已存在

    检查 CLAUDE.md 中的画像，如果缺失则通过引导问题采集。
    在 Claude Code 对话中，引导问题由 Agent (对话层) 处理；
    Pipeline 只负责检查存在性，不存在时返回空字符串。

    Returns:
        画像文本（可能为空）
    """
    persona_mgr = PersonaManager()
    persona_text = persona_mgr.get_persona_text()

    if persona_text:
        logger.info("✅ 用户画像已加载")
        return persona_text
    else:
        logger.warning("⚠ 未找到用户画像，将以无画像模式运行")
        return ""


def _extract_url(input_str: str) -> Optional[str]:
    """从字符串中提取播客 URL"""
    # 匹配 xiaoyuzhoufm.com 链接
    patterns = [
        r"https?://www\.xiaoyuzhoufm\.com/episode/[a-zA-Z0-9]+",
        r"https?://xiaoyuzhoufm\.com/episode/[a-zA-Z0-9]+",
        r"https?://www\.xiaoyuzhoufm\.com/episode/[a-zA-Z0-9]+\?[^\s]*",
    ]
    for pattern in patterns:
        match = re.search(pattern, input_str)
        if match:
            return match.group(0)
    return None


def run_pipeline(
    url: str,
    settings: Optional[AppSettings] = None,
    progress_callback=None,
) -> PipelineResult:
    """执行完整 Pipeline

    Args:
        url: 播客链接（小宇宙单集 URL）
        settings: 应用配置（可选）
        progress_callback: 进度回调 (stage: str, percent: int, message: str)

    Returns:
        PipelineResult

    Raises:
        AudioMindError: 任何阶段异常
    """
    if settings is None:
        settings = get_settings()

    start_time = time.time()
    project_root = Path(__file__).parent.parent

    # --- 阶段 0: 画像检查 ---
    persona_text = _ensure_persona(settings)

    # --- 阶段 1: 下载 ---
    logger.info("=" * 50)
    logger.info("Stage 1/3: 下载播客音频")
    logger.info("=" * 50)

    if progress_callback:
        progress_callback("download", 0, "正在获取播客信息...")

    episode = fetch_episode_metadata(url, settings=settings)
    logger.info(f"📻 {episode.podcast_name} - {episode.title}")

    # 超时检查
    _check_timeout(start_time, settings, "download-metadata")

    if progress_callback:
        progress_callback("download", 20, "正在下载音频文件...")

    temp_dir = project_root / settings.download.temp_dir
    audio_path = download_audio(episode, output_dir=temp_dir, settings=settings)

    if progress_callback:
        progress_callback("download", 100, "下载完成")

    # 超时检查
    _check_timeout(start_time, settings, "download")

    # --- 阶段 2: 转写 ---
    logger.info("=" * 50)
    logger.info("Stage 2/3: 语音转写")
    logger.info("=" * 50)

    # 长音频警告（本地 Whisper 时）
    _warn_long_audio(episode.duration_seconds, settings)

    if progress_callback:
        progress_callback("transcribe", 0, "开始语音转写...")

    provider = settings.transcriber.provider
    if provider == "volcengine":
        logger.info("使用火山引擎豆包语音识别（云端）")
        transcript = transcribe_volcengine(
            audio_path,
            settings=settings,
            public_url=episode.audio_url,
            episode_info=_build_episode_info(episode),
            progress_callback=lambda p, s: (
                progress_callback("transcribe", p, s) if progress_callback else None
            ),
        )
    elif provider == "alibaba":
        logger.info("使用阿里云智能语音交互（云端）")
        transcript = transcribe_alibaba(
            audio_path,
            settings=settings,
            public_url=episode.audio_url,
            progress_callback=lambda p, s: (
                progress_callback("transcribe", p, s) if progress_callback else None
            ),
        )
    else:
        logger.info(f"使用本地 faster-whisper 模型")
        transcript = transcribe(
            audio_path,
            settings=settings,
            progress_callback=lambda p, s: (
                progress_callback("transcribe", p, s) if progress_callback else None
            ),
        )

    if progress_callback:
        progress_callback("transcribe", 100, "转写完成")

    # 超时检查
    _check_timeout(start_time, settings, "transcribe")

    # --- 阶段 3: 分析 ---
    logger.info("=" * 50)
    logger.info("Stage 3/3: 内容分析")
    logger.info("=" * 50)

    if progress_callback:
        progress_callback("analyze", 0, "正在分析播客内容...")

    episode_info = _build_episode_info(episode)

    analysis = analyze_episode(
        transcript_text=transcript.full_text,
        persona_text=persona_text,
        episode_info=episode_info,
        settings=settings,
    )

    if progress_callback:
        progress_callback("analyze", 100, "分析完成")

    # 超时检查
    _check_timeout(start_time, settings, "analyze")

    # --- 生成输出 ---
    logger.info("=" * 50)
    logger.info("生成输出文档")
    logger.info("=" * 50)

    # 确定输出文件夹名
    folder_name = generate_folder_name(
        podcast_name=episode.podcast_name,
        episode_number=episode.episode_number,
        title=episode.title,
        max_topic_chars=settings.output.max_topic_chars,
    )

    output_dir = project_root / settings.output.base_dir / folder_name
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"输出目录: {output_dir}")

    # 生成文档
    transcript_md = TranscriptGenerator.generate(episode, transcript)
    transcript_path = TranscriptGenerator.save(
        transcript_md, output_dir, settings.output.transcript_file
    )

    insights_md = InsightsGenerator.generate(episode, analysis)
    insights_path = InsightsGenerator.save(
        insights_md, output_dir, settings.output.insights_file
    )

    # --- 清理临时音频 ---
    if audio_path.exists():
        try:
            audio_path.unlink()
            logger.info(f"临时音频已清理: {audio_path}")
        except Exception:
            pass

    # 尝试清理预处理 WAV
    wav_path = audio_path.with_suffix(".wav")
    if wav_path.exists():
        try:
            wav_path.unlink()
        except Exception:
            pass

    elapsed = time.time() - start_time
    logger.info(f"✅ Pipeline 完成! 总耗时: {elapsed:.0f}s")
    logger.info(f"   📄 转写: {transcript_path}")
    logger.info(f"   📄 洞察: {insights_path}")

    return PipelineResult(
        episode=episode,
        transcript=transcript,
        analysis=analysis,
        output_dir=str(output_dir),
        transcript_path=str(transcript_path),
        insights_path=str(insights_path),
    )


def main():
    """CLI 入口：python -m src.pipeline --url <播客链接>

    支持两种调用方式：
    1. 直接传 URL: python -m src.pipeline https://xiaoyuzhoufm.com/episode/xxx
    2. 标志参数: python -m src.pipeline --url https://xiaoyuzhoufm.com/episode/xxx
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="audio-mind: 播客洞察 Agent",
    )
    parser.add_argument(
        "url_or_input",
        nargs="?",
        help="播客链接（小宇宙单集 URL）",
    )
    parser.add_argument(
        "--url",
        dest="url_flag",
        help="播客链接（小宇宙单集 URL）",
    )
    parser.add_argument(
        "--no-cleanup",
        action="store_true",
        help="保留临时音频文件",
    )

    args = parser.parse_args()

    # 确定 URL
    input_str = args.url_or_input or args.url_flag or ""
    if not input_str:
        parser.print_help()
        sys.exit(1)

    extracted = _extract_url(input_str)
    if not extracted:
        print(f"错误: 无法从输入中提取有效的播客链接: {input_str}")
        print("支持格式: https://www.xiaoyuzhoufm.com/episode/xxxxx")
        sys.exit(1)

    # 加载配置
    try:
        settings = get_settings()
    except Exception as e:
        print(f"配置加载失败: {e}")
        sys.exit(1)

    # 执行 Pipeline
    try:
        result = run_pipeline(extracted, settings=settings)
        print(f"\n{'='*50}")
        print(f"Pipeline 完成!")
        print(f"{'='*50}")
        print(f"📻 {result.episode.podcast_name} - {result.episode.title}")
        print(f"📁 {result.output_dir}")
        print(f"📄 转写: {result.transcript_path}")
        print(f"📄 洞察: {result.insights_path}")
    except AudioMindError as e:
        print(f"\n错误: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n\n用户中断")
        sys.exit(130)


if __name__ == "__main__":
    main()
