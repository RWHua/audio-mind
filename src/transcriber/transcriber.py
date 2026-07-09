"""语音转写模块：faster-whisper + pydub 音频预处理

使用本地 faster-whisper large-v3 模型进行中文语音转写，
支持 VAD 静音过滤、长音频自动切片。
"""

import os
import time
from pathlib import Path
from typing import Optional

from pydub import AudioSegment

from src.exceptions import (
    AudioPreprocessError,
    WhisperModelError,
    WhisperRuntimeError,
)
from src.models import TranscriptSegment, TranscriptResult
from src.utils.config import get_settings, AppSettings
from src.utils.logger import setup_logger

logger = setup_logger("audio-mind.transcriber")


def preprocess_audio(audio_path: Path) -> Path:
    """音频预处理：用 ffmpeg 转为 16kHz mono WAV（faster-whisper 所需格式）

    直接使用 subprocess 调用 ffmpeg 进行重采样，避免 pydub 只改
    帧率头部而不实际重采样导致的时长/音调错误。

    Args:
        audio_path: 原始音频路径

    Returns:
        预处理后的 WAV 文件路径

    Raises:
        AudioPreprocessError: 预处理失败（缺少 ffmpeg 等）
    """
    import subprocess

    wav_path = audio_path.with_suffix(".wav")

    if wav_path.exists() and wav_path.stat().st_size > 0:
        logger.info(f"预处理文件已存在: {wav_path}")
        return wav_path

    logger.info(f"音频预处理: {audio_path.name} → 16kHz mono WAV")

    cmd = [
        "ffmpeg",
        "-y",                       # 覆盖已有文件
        "-i", str(audio_path),      # 输入
        "-ac", "1",                 # 单声道
        "-ar", "16000",             # 16kHz 采样率
        "-sample_fmt", "s16",       # 16-bit PCM
        "-f", "wav",                # WAV 格式
        str(wav_path),
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,  # 10 min 超时
        )
        if result.returncode != 0:
            raise AudioPreprocessError(
                "ffmpeg 音频预处理失败",
                detail=result.stderr.strip()[-500:],
            )
    except FileNotFoundError:
        raise AudioPreprocessError(
            "找不到 ffmpeg，请确认 ffmpeg 已安装并加入 PATH"
        )
    except subprocess.TimeoutExpired:
        raise AudioPreprocessError(
            "音频预处理超时（>10 分钟），请检查音频文件大小"
        )
    except Exception as e:
        raise AudioPreprocessError(
            "音频预处理异常",
            detail=str(e),
        )

    # 验证输出
    if not wav_path.exists() or wav_path.stat().st_size == 0:
        raise AudioPreprocessError("预处理后的 WAV 文件为空")

    # 用 pydub 读取验证实际时长
    try:
        audio = AudioSegment.from_file(str(wav_path))
        duration = len(audio) / 1000.0
    except Exception:
        duration = wav_path.stat().st_size / (16000 * 2)  # 16kHz 16bit mono

    logger.info(f"预处理完成: {wav_path} ({duration:.0f}s)")
    return wav_path


def _parse_timestamp(ts_str: str) -> str:
    """将秒数转回 HH:MM:SS 字符串"""
    seconds = float(ts_str)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _format_timestamp(start_seconds: float) -> str:
    """秒数 → [HH:MM:SS]"""
    h = int(start_seconds // 3600)
    m = int((start_seconds % 3600) // 60)
    s = int(start_seconds % 60)
    return f"[{h:02d}:{m:02d}:{s:02d}]"


def transcribe(
    audio_path: Path,
    settings: Optional[AppSettings] = None,
    progress_callback=None,
) -> TranscriptResult:
    """使用 faster-whisper 进行中文语音转写

    Args:
        audio_path: 预处理后的 WAV 文件路径
        settings: 应用配置
        progress_callback: 进度回调 (percent: int, status: str)

    Returns:
        TranscriptResult（含分段和全文）

    Raises:
        WhisperModelError: 模型加载失败
        WhisperRuntimeError: 转写运行时错误
    """
    if settings is None:
        settings = get_settings()

    cfg = settings.whisper

    # 预处理
    logger.info("开始音频预处理...")
    if progress_callback:
        progress_callback(0, "音频预处理...")
    wav_path = preprocess_audio(audio_path)

    # 加载模型
    logger.info(f"加载 faster-whisper 模型: {cfg.model}...")
    if progress_callback:
        progress_callback(5, f"加载 Whisper 模型 ({cfg.model})...")

    try:
        from faster_whisper import WhisperModel
        import torch

        # 确定设备和计算类型
        device = cfg.device
        compute_type = cfg.compute_type

        if device == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"
        if compute_type == "auto":
            compute_type = "float16" if device == "cuda" else "int8"

        logger.info(f"设备: {device}, 计算类型: {compute_type}")

        model = WhisperModel(
            cfg.model,
            device=device,
            compute_type=compute_type,
        )
    except Exception as e:
        raise WhisperModelError(
            f"faster-whisper 模型加载失败 ({cfg.model})",
            detail=str(e),
        )

    # 执行转写
    logger.info("开始语音转写...")
    if progress_callback:
        progress_callback(10, "正在转写音频...")

    try:
        segments_raw, info = model.transcribe(
            str(wav_path),
            language=cfg.language,
            beam_size=cfg.beam_size,
            vad_filter=cfg.vad_filter,
            vad_parameters=dict(
                threshold=cfg.vad_threshold,
            ) if cfg.vad_filter else None,
        )

        logger.info(f"检测语言: {info.language} (概率: {info.language_probability:.2%})")

        # 收集分段结果
        segments: list[TranscriptSegment] = []
        full_text_parts: list[str] = []
        last_progress = 10

        for seg in segments_raw:
            segments.append(
                TranscriptSegment(
                    start=seg.start,
                    end=seg.end,
                    text=seg.text.strip(),
                )
            )
            full_text_parts.append(seg.text.strip())

            # 进度回调（基于已处理的秒数占音频时长的比例）
            if progress_callback and wav_path.exists():
                try:
                    audio_dur = len(AudioSegment.from_file(str(wav_path))) / 1000.0
                    if audio_dur > 0:
                        progress = min(10 + int(80 * seg.end / audio_dur), 90)
                        if progress > last_progress:
                            last_progress = progress
                            progress_callback(progress, f"转写中... {seg.end:.0f}s / {audio_dur:.0f}s")
                except Exception:
                    pass

    except Exception as e:
        raise WhisperRuntimeError(
            "语音转写运行时错误",
            detail=str(e),
        )

    # 组装结果
    full_text = "\n".join(full_text_parts)

    # 获取音频时长
    try:
        audio_dur = len(AudioSegment.from_file(str(wav_path))) / 1000.0
    except Exception:
        audio_dur = segments[-1].end if segments else 0.0

    if progress_callback:
        progress_callback(95, "转写完成，整理结果...")

    result = TranscriptResult(
        segments=segments,
        full_text=full_text,
        language=cfg.language,
        duration=audio_dur,
    )

    logger.info(
        f"转写完成: {len(segments)} 个片段, "
        f"{len(full_text)} 字符, "
        f"~{result.token_estimate()} tokens"
    )

    return result
