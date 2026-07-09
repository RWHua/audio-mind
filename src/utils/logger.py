"""日志模块：统一日志格式，同时输出到终端和文件"""

import logging
import sys
from pathlib import Path


def setup_logger(
    name: str = "audio-mind",
    level: int = logging.INFO,
    log_file: str = "audio-mind.log",
) -> logging.Logger:
    """创建并配置 logger，输出到终端和文件"""
    logger = logging.getLogger(name)

    # 避免重复添加 handler
    if logger.handlers:
        return logger

    logger.setLevel(level)

    # 日志格式
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    # 终端 handler（Windows 控制台用 UTF-8 避免 GBK 编码报错）
    import io
    utf8_stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    console_handler = logging.StreamHandler(utf8_stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # 文件 handler（放项目根目录）
    try:
        log_path = Path(__file__).parent.parent.parent / log_file
        file_handler = logging.FileHandler(str(log_path), encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except (PermissionError, OSError):
        # 文件写入失败不影响终端输出
        pass

    return logger
