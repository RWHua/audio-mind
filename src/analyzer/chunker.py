"""文本分段模块：超长转写文本的智能分段

当 token 数超过阈值时，将文本分割为重叠段，供分段分析使用。
"""

import re
from typing import Optional

from src.utils.config import get_settings, AppSettings
from src.utils.logger import setup_logger

logger = setup_logger("audio-mind.analyzer.chunker")


class TextChunker:
    """文本分段器

    按句子边界分割，保证每段接近 target_size 字符，段间有 overlap 比例的重叠。
    分割优先级：段落边界 > 句子边界 > 短语边界 > 硬截断
    """

    def __init__(self, settings: Optional[AppSettings] = None):
        if settings is None:
            settings = get_settings()
        cfg = settings.chunking
        self.token_threshold = cfg.token_threshold
        self.chunk_size = cfg.chunk_size
        self.overlap = cfg.overlap

    def should_chunk(self, text: str) -> bool:
        """判断文本是否需要分段"""
        tokens_est = len(text) / 1.5  # 中文约 1.5 字符/token
        return tokens_est > self.token_threshold

    def chunk(self, text: str) -> list[str]:
        """将文本分割为重叠段

        Args:
            text: 完整文本

        Returns:
            分段文本列表
        """
        if not self.should_chunk(text):
            return [text]

        # 按句子分割
        sentences = self._split_sentences(text)

        chunks = []
        overlap_size = int(self.chunk_size * self.overlap)
        current = ""
        i = 0

        while i < len(sentences):
            sent = sentences[i]

            # 如果当前段加上这句不超限，加入
            if len(current) + len(sent) <= self.chunk_size:
                current += sent
                i += 1
            else:
                # 当前段已满
                if current:
                    chunks.append(current.strip())

                    # 回退 overlap 大小的文本作为新段起点
                    if overlap_size > 0 and len(current) > overlap_size:
                        overlap_text = current[-overlap_size:]
                        current = overlap_text
                    else:
                        current = ""
                else:
                    # 单句超长，硬截断
                    chunks.append(sent[:self.chunk_size].strip())
                    current = sent[self.chunk_size - overlap_size:] if overlap_size < len(sent) else ""
                    i += 1

        # 最后一段
        if current.strip():
            chunks.append(current.strip())

        logger.info(
            f"文本分段: {len(text)} 字符 → {len(chunks)} 段 "
            f"({self.chunk_size} 字/段, {self.overlap*100:.0f}% 重叠)"
        )

        return chunks

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        """按句子边界分割文本

        中文句子边界的标点：。！？\n
        保留标点符号在句子末尾。
        """
        # 在句子结束标点后分割，保留标点
        parts = re.split(r"(?<=[。！？\n])", text)
        return [p for p in parts if p.strip()]
