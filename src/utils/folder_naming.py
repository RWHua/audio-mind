"""文件夹命名模块：根据播客元数据生成输出文件夹名"""

import re

from src.utils.config import get_settings, AppSettings


def _sanitize(name: str) -> str:
    """清理文件夹名中的非法字符"""
    return re.sub(r'[\\/*?:"<>|]', "_", name)


def generate_folder_name(
    podcast_name: str,
    episode_number: str,
    title: str,
    max_topic_chars: int = 15,
) -> str:
    """生成输出文件夹名：{播客名}_{期号}_{简短主题}

    Args:
        podcast_name: 播客名称
        episode_number: 期号（如 E235）
        title: 单集标题
        max_topic_chars: 主题词最大字符数

    Returns:
        文件夹名（已清理非法字符）

    Examples:
        >>> generate_folder_name("知行小酒馆", "E235", "E235 与其担心 AI 改变你")
        "知行小酒馆_E235_AI改变你"
    """
    # 提取简短主题
    no_episode = re.sub(r"[Ee]\d+\s*", "", title).strip(" -，。-")

    # 截取最多 max_topic_chars 个中文字符
    if len(no_episode) <= max_topic_chars:
        topic = no_episode
    else:
        # 尝试在分隔符处截断
        parts = re.split(r"[，,：:\s\-—]", no_episode)
        topic = ""
        for p in parts:
            if not p:
                continue
            candidate = topic + p
            if len(candidate) <= max_topic_chars:
                topic = candidate
            else:
                break
        if not topic:
            topic = no_episode[:max_topic_chars]

    # 组装
    parts = []
    if podcast_name:
        parts.append(podcast_name)
    if episode_number:
        parts.append(episode_number)
    if topic:
        parts.append(topic)

    folder_name = "_".join(parts) if parts else "未命名播客"

    return _sanitize(folder_name)
