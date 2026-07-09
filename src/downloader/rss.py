"""RSS Feed 备选抓取路径

部分播客同时发布到 Apple Podcasts，RSS feed 作为小宇宙直接抓取失败时的降级方案。
"""

import re
from typing import Optional
from urllib.parse import urlparse, urljoin

import requests

from src.exceptions import PageFetchError, AudioExtractError
from src.models import EpisodeMetadata
from src.utils.http_client import create_http_session
from src.utils.logger import setup_logger

logger = setup_logger("audio-mind.downloader.rss")


def find_rss_feed(podcast_homepage: str) -> Optional[str]:
    """从播客主页查找 RSS feed URL

    尝试来源：
    1. <link type="application/rss+xml">
    2. 常见 RSS 路径（/feed, /rss, /podcast.xml）
    3. 已知小宇宙播客 RSS 模式

    Args:
        podcast_homepage: 播客主页 URL

    Returns:
        RSS feed URL 或 None
    """
    session = create_http_session(max_retries=2, timeout=30)

    try:
        resp = session.get(podcast_homepage)
        resp.raise_for_status()
    except Exception as e:
        logger.warning(f"无法访问播客主页: {podcast_homepage} - {e}")
        return None

    # 尝试从 HTML 提取 RSS link
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(resp.text, "lxml")

    # 方法 1: <link> 标签
    for link in soup.find_all("link"):
        if link.get("type") in ("application/rss+xml",):
            href = link.get("href", "")
            if href:
                return urljoin(podcast_homepage, href)

    # 方法 2: 尝试常见路径
    parsed = urlparse(podcast_homepage)
    base = f"{parsed.scheme}://{parsed.netloc}{parsed.path.rstrip('/')}"
    common_paths = ["/feed", "/feed.xml", "/rss", "/podcast.xml", "/feed/podcast/"]
    for path in common_paths:
        try:
            r = session.head(urljoin(base, path), timeout=10)
            if r.status_code == 200:
                return urljoin(base, path)
        except Exception:
            continue

    return None


def fetch_episode_from_rss(
    rss_url: str,
    episode_url: str,
) -> Optional[EpisodeMetadata]:
    """从 RSS feed 中搜索匹配的单集信息

    注意：此功能为降级方案，仅在小宇宙直接抓取失败时使用。
    由于不同播客 RSS 格式差异较大，支持有限。

    Args:
        rss_url: RSS feed URL
        episode_url: 原始小宇宙链接（用于匹配）

    Returns:
        EpisodeMetadata 或 None（未找到匹配单集）
    """
    import xml.etree.ElementTree as ET

    session = create_http_session(max_retries=2, timeout=30)

    try:
        resp = session.get(rss_url)
        resp.raise_for_status()
    except Exception as e:
        raise PageFetchError(
            f"RSS feed 访问失败: {rss_url}",
            detail=str(e),
        )

    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError as e:
        logger.warning(f"RSS XML 解析失败: {e}")
        return None

    # RSS 2.0 / iTunes Podcast 命名空间
    ns = {
        "itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd",
        "content": "http://purl.org/rss/1.0/modules/content/",
    }

    # 播客名
    podcast_name = ""
    title_el = root.find(".//channel/title")
    if title_el is not None and title_el.text:
        podcast_name = title_el.text

    # 遍历所有 item 查找匹配的单集
    for item in root.findall(".//item"):
        link_el = item.find("link")
        item_link = link_el.text if link_el is not None and link_el.text else ""

        # 通过链接匹配
        episode_id = _extract_id(episode_url)
        if episode_id and episode_id not in item_link:
            continue

        # 提取信息
        title = ""
        t = item.find("title")
        if t is not None and t.text:
            title = t.text

        # 音频 URL
        audio_url = ""
        enclosure = item.find("enclosure")
        if enclosure is not None:
            audio_url = enclosure.get("url", "")

        if not audio_url:
            continue

        # 时长
        duration_seconds = None
        dur = item.find("itunes:duration", ns)
        if dur is not None and dur.text:
            duration_seconds = _parse_rss_duration(dur.text)

        # 描述
        description = ""
        desc = item.find("description")
        if desc is not None and desc.text:
            description = desc.text

        episode = EpisodeMetadata(
            title=title,
            podcast_name=podcast_name,
            episode_number=_extract_episode_number(title),
            audio_url=audio_url,
            duration_seconds=duration_seconds,
            description=description,
            source_url=episode_url,
        )
        logger.info(f"RSS 解析成功: {podcast_name} - {title}")
        return episode

    logger.warning(f"RSS feed 中未找到匹配单集: {episode_url}")
    return None


def _extract_id(url: str) -> str:
    """从链接中提取播客/单集 ID"""
    # 小宇宙: /episode/6a06c4b91b7bd50295331e94
    match = re.search(r"/episode/([a-zA-Z0-9]+)", url)
    return match.group(1) if match else ""


def _extract_episode_number(title: str) -> str:
    """从标题提取期号"""
    match = re.search(r"[Ee](\d+)", title)
    return f"E{match.group(1)}" if match else ""


def _parse_rss_duration(text: str) -> Optional[int]:
    """解析 RSS 时长格式 (HH:MM:SS 或纯秒数)"""
    text = text.strip()
    # HH:MM:SS
    parts = text.split(":")
    if len(parts) == 3:
        try:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        except ValueError:
            pass
    # 纯数字（秒）
    try:
        return int(text)
    except ValueError:
        pass
    return None
