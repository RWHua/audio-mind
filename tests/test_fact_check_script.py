"""测试 scripts/fact_check.py（Tavily 事实核查脚本）

纯单元测试：mock 网络层（Tavily 搜索 / DeepSeek 判定），不发起真实 API 调用。
覆盖：输入校验、搜索失败降级、LLM 失败降级、报告生成、异常输入。
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# 确保能 import scripts/fact_check.py
BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))

import scripts.fact_check as fc  # noqa: E402


class TestMainInputValidation:
    """输入校验"""

    def test_no_args_shows_usage(self):
        """无参数 → 打印用法并退出 1"""
        with patch.object(sys, "argv", ["fact_check.py"]):
            with pytest.raises(SystemExit) as e:
                fc.main()
        assert e.value.code == 1

    def test_missing_tavily_key(self):
        """无 TAVILY_API_KEY → 报错退出"""
        with patch.object(fc, "TAVILY_KEY", ""), \
             patch.object(fc, "DEEPSEEK_KEY", "sk-test"), \
             patch.object(sys, "argv", ["fact_check.py", "claims.json"]):
            with pytest.raises(SystemExit) as e:
                fc.main()
        assert e.value.code == 1

    def test_missing_deepseek_key(self):
        """无 DEEPSEEK_API_KEY → 报错退出"""
        with patch.object(fc, "TAVILY_KEY", "tvly-test"), \
             patch.object(fc, "DEEPSEEK_KEY", ""), \
             patch.object(sys, "argv", ["fact_check.py", "claims.json"]):
            with pytest.raises(SystemExit) as e:
                fc.main()
        assert e.value.code == 1

    def test_invalid_claims_not_list(self, tmp_path):
        """claims.json 不是数组 → 报错退出"""
        bad = tmp_path / "bad.json"
        bad.write_text('{"not": "array"}', encoding="utf-8")
        with patch.object(fc, "TAVILY_KEY", "tvly-test"), \
             patch.object(fc, "DEEPSEEK_KEY", "sk-test"), \
             patch.object(sys, "argv", ["fact_check.py", str(bad)]):
            with pytest.raises(SystemExit) as e:
                fc.main()
        assert e.value.code == 1

    def test_claims_file_missing(self):
        """claims.json 不存在 → 抛异常"""
        with patch.object(fc, "TAVILY_KEY", "tvly-test"), \
             patch.object(fc, "DEEPSEEK_KEY", "sk-test"), \
             patch.object(sys, "argv", ["fact_check.py", "/nonexistent/claims.json"]):
            with pytest.raises(FileNotFoundError):
                fc.main()


class TestTavilySearch:
    """Tavily 搜索函数"""

    def test_success(self):
        """正常搜索返回结果列表"""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "results": [
                {"title": "t1", "url": "https://a.com", "content": "内容1"},
                {"title": "t2", "url": "https://b.com", "content": "内容2"},
            ]
        }).encode()
        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = mock_resp
        with patch("urllib.request.urlopen", return_value=mock_ctx):
            results = fc.tavily_search("测试查询")
        assert len(results) == 2
        assert results[0]["title"] == "t1"
        assert results[0]["url"] == "https://a.com"
        assert "内容1" in results[0]["content"]

    def test_empty_results(self):
        """搜索无结果 → 空列表"""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"results": []}).encode()
        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = mock_resp
        with patch("urllib.request.urlopen", return_value=mock_ctx):
            results = fc.tavily_search("无结果查询")
        assert results == []

    def test_content_truncated_to_300(self):
        """超长 content 截断到 300 字符"""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "results": [{"title": "t", "url": "u", "content": "长" * 1000}]
        }).encode()
        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = mock_resp
        with patch("urllib.request.urlopen", return_value=mock_ctx):
            results = fc.tavily_search("q")
        assert len(results[0]["content"]) <= 300

    def test_network_error_raises(self):
        """网络失败 → 异常向上抛（由调用方降级处理）"""
        with patch("urllib.request.urlopen", side_effect=Exception("network down")):
            with pytest.raises(Exception):
                fc.tavily_search("q")


class TestLLMJudge:
    """LLM 判定函数"""

    def test_success_parses_json(self):
        """LLM 返回 JSON → 解析成功"""
        from openai import OpenAI
        fake_completion = MagicMock()
        fake_completion.choices[0].message.content = json.dumps({
            "verdict": "✅已证实", "confidence": "高",
            "evidence": [{"source": "论文", "url": "https://x.com"}],
            "analysis": "官方论文直接支持", "usage_advice": "可引用",
        }, ensure_ascii=False)
        fake_client = MagicMock()
        fake_client.chat.completions.create.return_value = fake_completion
        with patch.object(fc, "DEEPSEEK_KEY", "sk-test"), \
             patch("openai.OpenAI", return_value=fake_client):
            result = fc.llm_judge({"claim": "x"}, [])
        assert result["verdict"] == "✅已证实"
        assert result["evidence"][0]["source"] == "论文"

    def test_non_json_response_fallback(self):
        """LLM 返回非 JSON → 降级为无法验证"""
        fake_completion = MagicMock()
        fake_completion.choices[0].message.content = "抱歉，我无法判断"
        fake_client = MagicMock()
        fake_client.chat.completions.create.return_value = fake_completion
        with patch.object(fc, "DEEPSEEK_KEY", "sk-test"), \
             patch("openai.OpenAI", return_value=fake_client):
            result = fc.llm_judge({"claim": "x"}, [])
        assert result["verdict"] == "⛔无法验证"
        assert "LLM 返回非 JSON" in result["analysis"]

    def test_api_error_raises(self):
        """API 调用异常 → 向上抛（由调用方降级处理）"""
        with patch.object(fc, "DEEPSEEK_KEY", "sk-test"), \
             patch("openai.OpenAI", side_effect=Exception("api down")):
            with pytest.raises(Exception):
                fc.llm_judge({"claim": "x"}, [])


class TestMainEndToEnd:
    """main() 端到端（mock 网络层）"""

    def test_full_flow_generates_report(self, tmp_path):
        """完整流程：搜索→判定→报告写入"""
        claims = tmp_path / "claims.json"
        claims.write_text(json.dumps([
            {"id": "c1", "claim": "DeepSeek V4 参数 1.6T", "source_note": "播客"},
        ]), encoding="utf-8")
        out = tmp_path / "report.md"

        # mock tavily_search 返回固定结果
        with patch.object(fc, "tavily_search", return_value=[
                {"title": "官方", "url": "https://deepseek.com", "content": "1.6T 49B"}]):
            # mock llm_judge 返回固定判定
            with patch.object(fc, "llm_judge", return_value={
                    "verdict": "✅已证实", "confidence": "高",
                    "evidence": [{"source": "官方", "url": "https://deepseek.com"}],
                    "analysis": "官方确认", "usage_advice": "可引用"}):
                with patch.object(sys, "argv", ["fact_check.py", str(claims), "--output", str(out)]):
                    with patch.object(fc, "TAVILY_KEY", "tvly-test"), \
                         patch.object(fc, "DEEPSEEK_KEY", "sk-test"):
                        fc.main()

        assert out.exists()
        content = out.read_text(encoding="utf-8")
        assert "事实核查报告" in content
        assert "c1" in content
        assert "✅已证实" in content
        assert "https://deepseek.com" in content

    def test_search_failure_degrades_to_unverifiable(self, tmp_path):
        """搜索失败 → 判定为无法验证，不崩溃"""
        claims = tmp_path / "claims.json"
        claims.write_text(json.dumps([{"id": "c1", "claim": "x"}]), encoding="utf-8")
        out = tmp_path / "report.md"

        with patch.object(fc, "tavily_search", side_effect=Exception("search down")), \
             patch.object(sys, "argv", ["fact_check.py", str(claims), "--output", str(out)]), \
             patch.object(fc, "TAVILY_KEY", "tvly-test"), \
             patch.object(fc, "DEEPSEEK_KEY", "sk-test"):
            fc.main()

        content = out.read_text(encoding="utf-8")
        assert "⛔无法验证" in content
        assert "Tavily 搜索无结果" in content

    def test_llm_failure_degrades_to_unverifiable(self, tmp_path):
        """LLM 判定失败 → 降级为无法验证，不崩溃"""
        claims = tmp_path / "claims.json"
        claims.write_text(json.dumps([{"id": "c1", "claim": "x"}]), encoding="utf-8")
        out = tmp_path / "report.md"

        with patch.object(fc, "tavily_search", return_value=[
                {"title": "t", "url": "u", "content": "c"}]):
            with patch.object(fc, "llm_judge", side_effect=Exception("llm down")):
                with patch.object(sys, "argv", ["fact_check.py", str(claims), "--output", str(out)]), \
                     patch.object(fc, "TAVILY_KEY", "tvly-test"), \
                     patch.object(fc, "DEEPSEEK_KEY", "sk-test"):
                    fc.main()

        content = out.read_text(encoding="utf-8")
        assert "⛔无法验证" in content
        assert "LLM 调用失败" in content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
