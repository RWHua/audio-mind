"""小宇宙 App 播客抓取模块

解析小宇宙分享页面（SSR）的 og:audio + JSON-LD，提取音频和元数据。
"""

import json
import re
import time
import os
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from src.exceptions import PageFetchError, AudioExtractError, AudioDownloadError
from src.models import EpisodeMetadata, PodcastShow
from src.utils.config import get_settings, AppSettings
from src.utils.http_client import create_http_session
from src.utils.logger import setup_logger

logger = setup_logger("audio-mind.downloader")


def parse_duration(duration_str: str) -> Optional[int]:
    """解析 ISO 8601 时长格式 PT82M -> 秒数"""
    if not duration_str:
        return None

    pattern = r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?"
    match = re.match(pattern, duration_str)
    if not match:
        return None

    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)
    return hours * 3600 + minutes * 60 + seconds


def _extract_episode_number(title: str) -> str:
    """从标题提取期号"""
    match = re.search(r"[Ee](\d+)", title)
    return f"E{match.group(1)}" if match else ""


def fetch_episode_metadata(url: str, settings: Optional[AppSettings] = None) -> EpisodeMetadata:
    """从小宇宙页面提取单集元数据

    策略：
    1. og:audio meta → 音频 URL
    2. schema:podcast-show JSON-LD → 完整元数据
    3. og:title → 标题（fallback）

    Args:
        url: 小宇宙单集链接（如 https://www.xiaoyuzhoufm.com/episode/xxx）
        settings: 应用配置（可选）

    Returns:
        EpisodeMetadata 实例

    Raises:
        PageFetchError: 页面抓取失败
        AudioExtractError: 音频链接提取失败
    """
    if settings is None:
        settings = get_settings()

    session = create_http_session(
        max_retries=settings.retry.max_attempts,
        backoff_factor=settings.retry.backoff_factor,
        timeout=30,
    )

    logger.info(f"抓取页面: {url}")
    try:
        resp = session.get(url)
        resp.raise_for_status()
    except Exception as e:
        raise PageFetchError(
            f"无法访问小宇宙页面: {url}",
            detail=str(e),
        )

    soup = BeautifulSoup(resp.text, "lxml")

    # --- 1. 提取音频 URL ---
    og_audio = soup.find("meta", property="og:audio")
    audio_url = None
    if og_audio and og_audio.get("content"):
        audio_url = og_audio["content"]
        logger.info(f"og:audio → {audio_url[:80]}...")
    else:
        raise AudioExtractError(
            "无法从页面提取音频链接",
            detail="未找到 <meta property='og:audio'> 标签",
        )

    # --- 2. 提取 JSON-LD 元数据 ---
    script_tag = soup.find("script", {"name": "schema:podcast-show"})
    json_ld = {}
    if script_tag and script_tag.string:
        try:
            json_ld = json.loads(script_tag.string)
        except json.JSONDecodeError:
            logger.warning("JSON-LD 解析失败，使用降级方案")

    # --- 3. 提取标题 ---
    title = ""
    if json_ld.get("name"):
        title = json_ld["name"]
    else:
        og_title = soup.find("meta", property="og:title")
        if og_title:
            title = og_title.get("content", "")

    if not title:
        title = soup.title.string if soup.title else "未知标题"

    # --- 4. 提取播客名 ---
    podcast_name = ""
    show = None
    if json_ld.get("partOfSeries"):
        series = json_ld["partOfSeries"]
        podcast_name = series.get("name", "")
        show = PodcastShow(
            name=podcast_name,
            url=series.get("url", ""),
        )

    # --- 5. 提取时长 ---
    duration_str = json_ld.get("timeRequired", "")
    duration_seconds = parse_duration(duration_str)

    # --- 6. 提取描述/节目笔记 ---
    description = json_ld.get("description", "")

    # --- 7. 提取封面 ---
    cover_url = ""
    og_image = soup.find("meta", property="og:image")
    if og_image:
        cover_url = og_image.get("content", "")

    episode = EpisodeMetadata(
        title=title,
        podcast_name=podcast_name,
        episode_number=_extract_episode_number(title),
        audio_url=audio_url,
        cover_url=cover_url,
        duration_seconds=duration_seconds,
        description=description,
        source_url=url,
        show=show,
    )

    logger.info(f"元数据解析完成: {episode.podcast_name} - {episode.title}")
    return episode


def _make_safe_filename(episode: EpisodeMetadata) -> str:
    """生成安全的文件名"""
    ext = os.path.splitext(episode.audio_url.split("?")[0])[1] or ".m4a"
    safe_name = re.sub(r'[\\/*?:"<>|]', "_", f"{episode.episode_number}_{episode.podcast_name}")
    return f"{safe_name}{ext}"


def download_audio(
    episode: EpisodeMetadata,
    output_dir: Optional[Path] = None,
    settings: Optional[AppSettings] = None,
) -> Path:
    """流式下载音频文件，支持断点续传

    当 download.resume=True（默认）且目标文件已部分存在时，
    通过 HTTP Range 头从断点处继续下载，避免重复传输。

    Args:
        episode: 单集元数据
        output_dir: 输出目录（None 则使用配置的 temp_dir）
        settings: 应用配置

    Returns:
        下载后的文件路径

    Raises:
        AudioDownloadError: 下载失败
    """
    if settings is None:
        settings = get_settings()

    if output_dir is None:
        root = Path(__file__).parent.parent.parent
        output_dir = root / settings.download.temp_dir

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    filename = _make_safe_filename(episode)
    filepath = output_dir / filename

    session = create_http_session(
        max_retries=2,
        backoff_factor=2.0,
        timeout=settings.download.timeout,
    )

    logger.info(f"开始下载: {episode.audio_url[:80]}...")
    logger.info(f"保存到: {filepath}")

    # ── 断点续传：检查已有部分文件 ──
    downloaded = 0
    headers = {}
    if settings.download.resume and filepath.exists():
        existing_size = filepath.stat().st_size
        if existing_size > 0:
            logger.info(
                f"检测到已有文件 {existing_size / 1024 / 1024:.1f} MB，尝试续传..."
            )
            headers["Range"] = f"bytes={existing_size}-"

    try:
        resp = session.get(episode.audio_url, stream=True, headers=headers)

        if resp.status_code == 206:
            # 服务器支持断点续传
            logger.info(
                f"服务器支持续传 (206 Partial Content)，"
                f"从 {downloaded} 字节处继续"
            )
            total_size = int(resp.headers.get("Content-Length", 0))
            mode = "ab"
            downloaded = filepath.stat().st_size if filepath.exists() else 0
            total_size += downloaded
        elif resp.status_code == 200 and headers:
            # 服务器不支持续传，从头下载
            logger.info("服务器不支持续传 (200 OK)，将重新下载")
            total_size = int(resp.headers.get("Content-Length", 0))
            mode = "wb"
            downloaded = 0
        else:
            resp.raise_for_status()
            total_size = int(resp.headers.get("Content-Length", 0))
            mode = "wb"
            downloaded = 0

        start_time = time.time()

        with open(filepath, mode) as f:
            for chunk in resp.iter_content(chunk_size=settings.download.chunk_size):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)

                    # 进度日志（每 10% 输出一次）
                    if total_size > 0:
                        pct = downloaded / total_size
                        elapsed = time.time() - start_time
                        speed = downloaded / elapsed / 1024 if elapsed > 0 else 0
                        logger.debug(
                            f"下载进度: {pct*100:.0f}% "
                            f"({downloaded/1024/1024:.1f}MB / {total_size/1024/1024:.1f}MB) "
                            f"速度: {speed:.0f} KB/s"
                        )

        elapsed = time.time() - start_time
        file_size_mb = filepath.stat().st_size / 1024 / 1024
        logger.info(
            f"下载完成: {file_size_mb:.1f}MB "
            f"耗时 {elapsed:.0f}s "
            f"平均 {file_size_mb/elapsed*1024:.0f} KB/s"
        )

        return filepath

    except Exception as e:
        # 保留不完整文件以便下次续传
        if filepath.exists():
            partial_mb = filepath.stat().st_size / 1024 / 1024
            logger.warning(
                f"下载中断，已保留 {partial_mb:.1f} MB 用于下次续传"
            )
        raise AudioDownloadError(
            "音频下载失败",
            detail=str(e),
        )


def fetch_and_download(
    url: str,
    output_dir: Optional[Path] = None,
    settings: Optional[AppSettings] = None,
) -> tuple[EpisodeMetadata, Path]:
    """一步完成：提取元数据 + 下载音频

    Returns:
        (EpisodeMetadata, 音频文件路径)
    """
    if settings is None:
        settings = get_settings()

    episode = fetch_episode_metadata(url, settings=settings)
    audio_path = download_audio(episode, output_dir=output_dir, settings=settings)
    return episode, audio_path
