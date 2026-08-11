"""测试 prompt 模板安全替换（apply_template）与事实核查模板

覆盖对抗性场景：
- 二次替换污染（内容含其他占位符字面量）
- 缺失变量 / 空值 / 特殊字符 / 超长内容
- fact_check.yaml 模板完整性
- 并发安全
"""

import json

import pytest

from src.analyzer.client import apply_template, load_prompt


class TestApplyTemplate:
    """安全模板替换"""

    def test_basic_substitution(self):
        """基础替换"""
        result = apply_template("你好{{name}}，今天{{weather}}", {"name": "阿Hua", "weather": "晴"})
        assert result == "你好阿Hua，今天晴"

    def test_no_double_replacement(self):
        """内容里的 {{其他占位符}} 字面量不被二次替换（核心防污染）"""
        persona = "我的兴趣是{{episode_info}}和{{transcript}}"
        episode = "标题含{{transcript}}"
        result = apply_template(
            "画像:{{persona}}|集:{{episode_info}}|文:{{transcript}}",
            {"persona": persona, "episode_info": episode, "transcript": "正文"},
        )
        # 所有字面量必须原样保留
        assert "{{episode_info}}" in result
        assert "{{transcript}}" in result
        assert "正文" in result

    def test_self_reference_not_expanded(self):
        """值里含自身占位符字面量也不展开"""
        result = apply_template("{{x}}", {"x": "值{{x}}"})
        assert result == "值{{x}}"

    def test_missing_variable_kept(self):
        """缺失变量原样保留（便于发现未替换）"""
        result = apply_template("a{{missing}}b", {"other": "x"})
        assert result == "a{{missing}}b"

    def test_empty_value(self):
        """空值正常替换"""
        result = apply_template("[{{p}}]", {"p": ""})
        assert result == "[]"

    def test_control_chars_passthrough(self):
        """控制字符/NULL 透传不丢"""
        result = apply_template("{{t}}", {"t": "a\u0000b"})
        assert result == "a\u0000b"

    def test_huge_value_performance(self):
        """1M 字符值替换不崩（性能）"""
        import time

        big = "长" * 1_000_000
        t0 = time.monotonic()
        result = apply_template("{{x}}", {"x": big})
        assert len(result) == 1_000_000
        assert time.monotonic() - t0 < 3

    def test_unknown_braces_untouched(self):
        """非 {{word}} 格式的花括号不受影响"""
        result = apply_template("价格{100}元", {"x": "y"})
        assert result == "价格{100}元"

    def test_unicode_and_newlines(self):
        """中文/换行内容正常"""
        result = apply_template("{{p}}", {"p": "多行\n文本，中文。"})
        assert "多行\n文本，中文。" in result


class TestFactCheckTemplate:
    """fact_check.yaml 模板完整性（供任何 Agent 复用）"""

    def test_template_loads(self):
        """模板可加载且有 system/user"""
        sys_p, usr_p = load_prompt("fact_check")
        assert sys_p and usr_p

    def test_required_placeholders(self):
        """必需占位符齐全"""
        _, usr_p = load_prompt("fact_check")
        assert "{{claims}}" in usr_p
        assert "{{source_context}}" in usr_p

    def test_verdict_lexicon(self):
        """判定等级词表完整"""
        sys_p, _ = load_prompt("fact_check")
        for kw in ["已证实", "多方印证", "存疑", "证伪", "无法验证"]:
            assert kw in sys_p, f"词表缺: {kw}"

    def test_schema_fields(self):
        """输出 JSON schema 字段完整（在 user 段的 JSON 示例中）"""
        _, usr_p = load_prompt("fact_check")
        for kw in ["claim_id", "verdict", "confidence", "evidence", "usage_advice"]:
            assert kw in usr_p, f"schema 缺字段: {kw}"

    def test_claims_with_placeholder_literal(self):
        """claims 内容含 {{source_context}} 字面量不被污染"""
        _, usr_p = load_prompt("fact_check")
        evil = '{"id":"c1","claim":"含{{source_context}}字面量"}'
        result = apply_template(usr_p, {"claims": evil, "source_context": "背景"})
        assert "{{source_context}}" in result  # 字面量保留
        assert "背景" in result  # 真实占位符被替换


class TestAnalyzeSynthesizeTemplates:
    """analyze/synthesize 模板（pipeline 实际使用的）"""

    def test_analyze_placeholders(self):
        """analyze 必需占位符齐全"""
        _, usr_p = load_prompt("analyze")
        for kw in ["{{persona}}", "{{episode_info}}", "{{transcript}}"]:
            assert kw in usr_p

    def test_synthesize_placeholders(self):
        _, usr_p = load_prompt("synthesize")
        for kw in ["{{persona}}", "{{episode_info}}", "{{chunk_summaries}}"]:
            assert kw in usr_p

    def test_analyze_grading_rules_present(self):
        """事实/观点分级 + 核心技能过滤规则已写入"""
        sys_p, usr_p = load_prompt("analyze")
        full = sys_p + usr_p
        for kw in ["证据等级", "官方公告", "主播转述", "个人推测", "核心技能", "评估体系"]:
            assert kw in full, f"analyze 缺规则: {kw}"

    def test_action_items_core_skill_filter(self):
        """行动项必须对应核心技能（背景知识禁止）"""
        sys_p, usr_p = load_prompt("analyze")
        full = sys_p + usr_p
        assert "背景知识" in full
        assert "禁止进入 action_items" in full or "禁止作为行动项" in full

    def test_concurrent_template_loading(self):
        """并发加载+替换互不干扰"""
        from concurrent.futures import ThreadPoolExecutor

        def worker(i):
            _, usr_p = load_prompt("analyze")
            result = apply_template(usr_p, {
                "persona": f"画像{i}",
                "episode_info": f"集{i}",
                "transcript": f"文{i}",
            })
            return f"画像{i}" in result and f"集{i}" in result and f"文{i}" in result

        with ThreadPoolExecutor(max_workers=8) as ex:
            results = list(ex.map(worker, range(8)))
        assert all(results)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
