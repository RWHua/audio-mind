"""测试分析合成模块的 JSON 修复回路（_parse_with_repair）

纯单元测试（不标 integration）：
- 用 MagicMock 模拟 DeepSeekClient.chat，不发起真实 API 调用
- 覆盖：合法 JSON 直接通过 / 语法错误修复 / 结构错误修复 / 修复超限抛错
"""

import json

import pytest
from unittest.mock import MagicMock

from src.exceptions import AnalysisError, SynthesisError
from src.analyzer.synthesizer import _parse_with_repair, MAX_JSON_REPAIRS


def _valid_json() -> str:
    """构造一份合法的分析结果 JSON"""
    return json.dumps(
        {
            "core_viewpoints": [{"title": "观点1", "detail": "详情1"}],
            "personal_relevance": [{"title": "关联1", "detail": "详情2"}],
            "action_items": [{"action": "行动1", "reason": "原因1", "difficulty": "低"}],
            "key_quotations": [{"text": "引述1", "context": "背景1", "timestamp_approx": "12:30"}],
            "controversial_points": [{"claim": "观点A", "reason": "可能有问题"}],
            "resources_mentioned": [{"name": "资源1", "type": "工具", "description": "介绍1"}],
        },
        ensure_ascii=False,
    )


def _make_client(return_value: str) -> MagicMock:
    """构造 mock 客户端，chat 固定返回给定内容"""
    client = MagicMock()
    client.chat.return_value = return_value
    return client


class TestParseWithRepair:
    """JSON 修复回路测试"""

    def test_valid_json_no_repair_call(self):
        """合法 JSON 直接解析成功，不触发修复调用"""
        client = _make_client("")
        result = _parse_with_repair(_valid_json(), client)

        assert len(result.core_viewpoints) == 1
        assert result.core_viewpoints[0].title == "观点1"
        assert len(result.action_items) == 1
        client.chat.assert_not_called()

    def test_syntax_error_repaired(self):
        """JSON 语法错误 → 触发 1 次修复调用并成功"""
        bad_json = '{"core_viewpoints": [{"title": "观点1", "detail": "详情1"}]'  # 缺右括号
        client = _make_client(_valid_json())

        result = _parse_with_repair(bad_json, client)

        assert result.core_viewpoints[0].title == "观点1"
        assert client.chat.call_count == 1
        # 验证修复 prompt 拿到了原始输出和错误信息
        args = client.chat.call_args[0]  # 位置参数: (sys_prompt, usr_prompt)
        sys_prompt, usr_prompt = args
        assert "{{original_output}}" not in usr_prompt  # 变量已被替换
        assert bad_json in usr_prompt

    def test_structure_error_repaired(self):
        """合法 JSON 但结构错误（缺必填字段）→ 触发修复成功"""
        # title 缺失 → pydantic ValidationError
        bad_structure = json.dumps(
            {"core_viewpoints": [{"detail": "没有title"}], "action_items": []},
            ensure_ascii=False,
        )
        client = _make_client(_valid_json())

        result = _parse_with_repair(bad_structure, client)

        assert len(result.core_viewpoints) == 1
        assert client.chat.call_count == 1

    def test_repair_exhausted_raises(self):
        """修复 2 次仍失败 → 抛 SynthesisError，且不重复修复第 3 次"""
        always_bad = "still not json {{{"
        client = _make_client(always_bad)

        with pytest.raises(SynthesisError) as exc_info:
            _parse_with_repair("bad start", client, max_repairs=MAX_JSON_REPAIRS)

        assert "修复" in str(exc_info.value)
        # 初始解析 1 次 + 修复 2 次 = chat 恰好被调用 2 次
        assert client.chat.call_count == MAX_JSON_REPAIRS

    def test_repair_failure_includes_original(self):
        """失败时异常 detail 携带原始响应，便于排查"""
        original = '{"core_viewpoints": [{'  # 严重截断
        client = _make_client("still bad")

        with pytest.raises(SynthesisError) as exc_info:
            _parse_with_repair(original, client)

        assert original[:500] in str(exc_info.value)

    def test_analysis_error_still_analysis_error_on_valid_parse_path(self):
        """_parse_analysis_json 的原始报错类型仍是 AnalysisError（回归保护）"""
        from src.analyzer.synthesizer import _parse_analysis_json

        with pytest.raises(AnalysisError):
            _parse_analysis_json("not json at all")

    # ============ 对抗性测试（异常输入 / 边界值 / 网络失败 / 错误假设） ============

    def test_none_input_repaired(self):
        """None 输入不再崩溃，而是触发修复回路"""
        client = _make_client(_valid_json())
        result = _parse_with_repair(None, client)
        assert len(result.core_viewpoints) == 1
        assert client.chat.call_count == 1

    def test_top_level_array_repaired(self):
        """顶层是数组（非对象）→ 触发修复而非 AttributeError 冒泡"""
        client = _make_client(_valid_json())
        result = _parse_with_repair('[{"title": "x", "detail": "y"}]', client)
        assert len(result.core_viewpoints) == 1
        assert client.chat.call_count == 1

    def test_top_level_scalar_repaired(self):
        """顶层是字符串/数字 → 触发修复而非 AttributeError 冒泡"""
        for bad in ['"hello"', "123"]:
            client = _make_client(_valid_json())
            result = _parse_with_repair(bad, client)
            assert len(result.core_viewpoints) == 1
            assert client.chat.call_count == 1

    def test_field_dict_instead_of_list_repaired(self):
        """字段是 dict 而非 list → 触发修复而非 TypeError 冒泡"""
        bad = json.dumps({"core_viewpoints": {"title": "t", "detail": "d"}}, ensure_ascii=False)
        client = _make_client(_valid_json())
        result = _parse_with_repair(bad, client)
        assert len(result.core_viewpoints) == 1
        assert client.chat.call_count == 1

    def test_list_element_not_mapping_repaired(self):
        """列表元素是 str 而非对象 → 触发修复而非 TypeError 冒泡"""
        bad = json.dumps({"core_viewpoints": ["abc"]}, ensure_ascii=False)
        client = _make_client(_valid_json())
        result = _parse_with_repair(bad, client)
        assert len(result.core_viewpoints) == 1
        assert client.chat.call_count == 1

    def test_repair_output_with_codeblock(self):
        """修复返回带 ```json 代码块 → 提取后成功，只调用 1 次（不浪费修复次数）"""
        client = _make_client("```json\n" + _valid_json() + "\n```")
        result = _parse_with_repair("bad json", client)
        assert len(result.core_viewpoints) == 1
        assert client.chat.call_count == 1

    def test_repair_output_empty_consumes_attempts(self):
        """修复返回空串 → 无效，正确消耗修复次数后抛 SynthesisError"""
        client = _make_client("")
        with pytest.raises(SynthesisError):
            _parse_with_repair("bad json", client, max_repairs=2)
        assert client.chat.call_count == 2

    def test_max_repairs_zero_immediate_fail(self):
        """max_repairs=0 → 不修复，直接抛 SynthesisError，chat 不被调用"""
        client = _make_client(_valid_json())
        with pytest.raises(SynthesisError):
            _parse_with_repair("bad json", client, max_repairs=0)
        client.chat.assert_not_called()

    def test_network_failure_propagates_llm_error(self):
        """修复调用网络失败 → LLMAPIError 冒泡，不吞异常不无限重试"""
        from src.exceptions import LLMAPIError

        client = MagicMock()
        client.chat.side_effect = LLMAPIError("DeepSeek API 调用失败", detail="connection refused")
        with pytest.raises(LLMAPIError):
            _parse_with_repair("bad json", client)
        assert client.chat.call_count == 1  # 不重试

    def test_template_placeholder_not_double_replaced(self):
        """原始输出含 {{error_detail}} 字面量 → 不被二次替换污染"""
        evil = '{"core_viewpoints": [{"title": "{{error_detail}}", "detail": "x"}]'  # 坏 JSON 触发修复
        client = _make_client(_valid_json())
        result = _parse_with_repair(evil, client)
        assert len(result.core_viewpoints) == 1
        # 验证传入修复 prompt 的原始输出未被污染
        usr_prompt = client.chat.call_args[0][1]
        assert "{{error_detail}}" in usr_prompt  # 字面量保留

    def test_concurrent_calls_isolated(self):
        """并发调用互不干扰（无共享状态）"""
        from concurrent.futures import ThreadPoolExecutor

        def worker(i):
            c = _make_client(_valid_json())
            bad = '{"core_viewpoints": [{"title": "t%d", "detail": "d"}]' % i
            try:
                r = _parse_with_repair(bad, c)
                return ("ok", r.core_viewpoints[0].title, c.chat.call_count)
            except Exception as e:
                return ("err", type(e).__name__, str(e)[:50])

        with ThreadPoolExecutor(max_workers=8) as ex:
            results = list(ex.map(worker, range(8)))

        assert all(r[0] == "ok" for r in results)
        assert all(r[2] == 1 for r in results)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
