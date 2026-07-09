"""测试文本分段模块"""

import pytest
from src.analyzer.chunker import TextChunker


class TestTextChunker:
    """文本分段器测试"""

    def test_short_text_no_chunk(self):
        """短文本不触发分段"""
        chunker = TextChunker()
        text = "这是一个短文本。只有几句话。不需要分段。"
        assert not chunker.should_chunk(text)
        chunks = chunker.chunk(text)
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_should_chunk(self):
        """token 阈值判断"""
        chunker = TextChunker()
        chunker.token_threshold = 100  # ~150 字符
        short = "短" * 100
        long = "长" * 2000
        assert not chunker.should_chunk(short)
        assert chunker.should_chunk(long)

    def test_chunk_split(self):
        """分段结果"""
        chunker = TextChunker()
        chunker.token_threshold = 10
        chunker.chunk_size = 100
        chunker.overlap = 0.1

        # 构造超长文本（每个句子以。结尾）
        sentences = [f"这是第{i}个测试句子。" for i in range(20)]
        text = "".join(sentences)

        chunks = chunker.chunk(text)
        assert len(chunks) > 1
        for chunk in chunks:
            assert len(chunk) <= chunker.chunk_size + 50  # 允许一定误差

    def test_sentence_split(self):
        """句子分割"""
        text = "这是第一句话。这是第二句话！这是第三句话？\n这是第四句。"
        sentences = TextChunker._split_sentences(text)
        assert len(sentences) >= 3

    def test_empty_text(self):
        """空文本"""
        chunker = TextChunker()
        assert chunker.chunk("") == [""]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
