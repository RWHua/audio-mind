# -*- coding: utf-8 -*-
"""事实核查脚本：Tavily 搜索 + LLM 判定（任何 Agent 可独立运行）

用法（不依赖 Hermes）:
    python scripts/fact_check.py claims.json --output report.md
    python scripts/fact_check.py claims.json --llm deepseek --output report.md

输入 claims.json:
    [{"id": "c1", "claim": "DeepSeek V4 单token推理FLOPs为V3.2的27%", "source_note": "播客23:03"}]

依赖: .env 中 TAVILY_API_KEY（Tavily 搜索）+ DEEPSEEK_API_KEY（LLM 判定）
"""
import io
import json
import os
import re
import sys
import urllib.request
import urllib.error

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

# 加载 .env（手写解析，避免依赖 python-dotenv 未装）
def load_env():
    env_path = os.path.join(BASE, ".env")
    env = {}
    if os.path.exists(env_path):
        for line in open(env_path, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env

ENV = load_env()
TAVILY_KEY = ENV.get("TAVILY_API_KEY", os.environ.get("TAVILY_API_KEY", ""))
DEEPSEEK_KEY = ENV.get("DEEPSEEK_API_KEY", os.environ.get("DEEPSEEK_API_KEY", ""))


def tavily_search(query: str, max_results: int = 3) -> list[dict]:
    """Tavily 搜索（REST API 直调，不依赖任何 Agent 工具）"""
    req = urllib.request.Request(
        "https://api.tavily.com/search",
        data=json.dumps({"query": query, "max_results": max_results}).encode(),
        headers={"Authorization": "Bearer " + TAVILY_KEY, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        d = json.loads(r.read())
    return [
        {"title": x.get("title", ""), "url": x.get("url", ""),
         "content": (x.get("content", "") or "")[:300]}
        for x in d.get("results", [])
    ]


def llm_judge(claim: dict, search_results: list[dict]) -> dict:
    """DeepSeek 判定证据等级（OpenAI 兼容接口）"""
    from openai import OpenAI
    client = OpenAI(api_key=DEEPSEEK_KEY, base_url="https://api.deepseek.com", timeout=60)

    sys_prompt = """你是一位严谨的事实核查员。根据提供的搜索结果，判定主张的证据等级。
等级词表（严格使用）：
- ✅已证实：官方公告/论文/权威一手来源直接支持
- 🔶多方印证：2个以上独立来源一致支持
- ⚠️存疑：仅单一来源/内部消息/个人转述
- ❌证伪：与权威来源矛盾
- ⛔无法验证：检索不到可靠来源
只输出 JSON：{"verdict": "等级", "confidence": "高/中/低", "evidence": [{"source": "来源名", "url": "链接"}], "analysis": "判定理由2-3句", "usage_advice": "引用建议"}"""

    user_prompt = f"""## 待核查主张
{json.dumps(claim, ensure_ascii=False)}

## 搜索结果
{json.dumps(search_results, ensure_ascii=False, indent=2)}"""

    resp = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "system", "content": sys_prompt},
                  {"role": "user", "content": user_prompt}],
        max_tokens=800, temperature=0.3,
    )
    text = resp.choices[0].message.content or ""
    # 提取 JSON
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        return json.loads(m.group(0))
    return {"verdict": "⛔无法验证", "confidence": "低", "evidence": [], "analysis": f"LLM 返回非 JSON: {text[:100]}", "usage_advice": "建议人工核查"}


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    claims_path = sys.argv[1]
    output_path = None
    for i, a in enumerate(sys.argv):
        if a == "--output" and i + 1 < len(sys.argv):
            output_path = sys.argv[i + 1]

    if not TAVILY_KEY:
        print("❌ 未配置 TAVILY_API_KEY（检查 .env）")
        sys.exit(1)
    if not DEEPSEEK_KEY:
        print("❌ 未配置 DEEPSEEK_API_KEY（检查 .env）")
        sys.exit(1)

    claims = json.loads(open(claims_path, encoding="utf-8").read())
    if not isinstance(claims, list):
        print("❌ claims.json 必须是数组")
        sys.exit(1)

    print(f"待核查 {len(claims)} 条主张...")
    results = []
    for i, claim in enumerate(claims, 1):
        q = claim.get("claim", "")[:80]
        print(f"[{i}/{len(claims)}] 搜索: {q}")
        try:
            sr = tavily_search(q)
        except Exception as e:
            print(f"  搜索失败: {e}")
            sr = []
        if not sr:
            results.append({"claim_id": claim.get("id", f"c{i}"), "claim": claim.get("claim", ""),
                            "verdict": "⛔无法验证", "confidence": "低", "evidence": [],
                            "analysis": "Tavily 搜索无结果", "usage_advice": "建议人工核查"})
            continue
        print(f"  搜索到 {len(sr)} 条，LLM 判定中...")
        try:
            verdict = llm_judge(claim, sr)
        except Exception as e:
            print(f"  LLM 判定失败: {e}")
            verdict = {"verdict": "⛔无法验证", "confidence": "低", "evidence": [],
                       "analysis": f"LLM 调用失败: {str(e)[:80]}", "usage_advice": "建议人工核查"}
        verdict["claim_id"] = claim.get("id", f"c{i}")
        verdict["claim"] = claim.get("claim", "")
        results.append(verdict)

    # 输出报告
    md = ["## 🔍 事实核查报告", "", f"> 来源: Tavily 搜索 + DeepSeek 判定 | {__import__('datetime').date.today()}", ""]
    for r_ in results:
        md.append(f"### {r_['claim_id']}. {r_['claim']}")
        md.append(f"- **判定**: {r_['verdict']} (置信度 {r_['confidence']})")
        if r_.get("evidence"):
            md.append("- **证据**:")
            for e in r_["evidence"]:
                md.append(f"  - {e.get('source','')} — {e.get('url','')}")
        md.append(f"- **分析**: {r_['analysis']}")
        md.append(f"- **引用建议**: {r_['usage_advice']}")
        md.append("")

    report = "\n".join(md)
    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"\n✅ 报告已写入: {output_path}")
    else:
        print(report)


if __name__ == "__main__":
    # CLI 入口才重定向 stdout（修复 Windows GBK 编码）；被 import/测试时不改，
    # 避免污染宿主进程的 stdout
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    main()
