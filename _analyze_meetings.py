"""分析三次需求串讲会议，提取完整流程信息"""
import sys, time, re
from pathlib import Path

PROJECT = Path(r"D:\vibecoding\project\Agents\audio-mind")
sys.path.insert(0, str(PROJECT / "src"))

from src.analyzer.client import DeepSeekClient
from src.analyzer.chunker import TextChunker
from src.utils.config import get_settings

TRANS_DIR = Path(r"D:\knowledge\newKnowledge\项目0713\会议录音及转写\转写")

# 合并所有转写（去重：跳过说话人识别无关人员）
parts = []
for f in sorted(TRANS_DIR.glob("*.md")):
    content = f.read_text(encoding="utf-8")
    parts.append(f"## {f.stem}\n\n{content}")

full_text = "\n\n---\n\n".join(parts)
est_tokens = len(full_text) // 2
print(f"总字符: {len(full_text)}, 估算 tokens: {est_tokens}")

# 问题和分段
question = """
请根据以上三次需求串讲会议的全部内容，系统性地回答以下问题：

## 1. 完整流程图
从「用户上传 OD Excel」到「PN 发布」的每一步，标注：
- 步骤编号和名称
- 谁执行（Planner / TPM / BOM团队 / AI Agent / Venture系统自动）
- 输入是什么、输出是什么
- 是否有人的确认/审核节点

## 2. 关键术语
用通俗语言解释：Local CV / Global CV / Super Bomb(98) / 69 Part / 86层 / PTO(Transceiver) / XCVR Checklist / System Checklist / POR / NPIR / PCR / Sourcing Plan / Load Sheet / Low Sheet

## 3. AI vs 非AI分工
哪些步骤用AI，哪些不用，各自的理由是什么。

## 4. 纠错
我之前告诉用户的一些理解，如果和会议内容有出入，请逐一纠正。

## 5. 关键决策和约束
会上达成的重要共识、硬性时间节点、技术约束。
"""

# 分段
chunker = TextChunker()
if chunker.should_chunk(full_text):
    chunks = chunker.chunk(full_text)
else:
    chunks = [full_text]
print(f"分为 {len(chunks)} 段")

# 逐段分析
settings = get_settings()
client = DeepSeekClient(settings)
results = []

for i, chunk in enumerate(chunks):
    print(f"\n{'='*50}")
    print(f"分析第 {i+1}/{len(chunks)} 段 ({len(chunk)} 字符, ~{len(chunk)//2} tokens)...")
    t0 = time.time()

    try:
        resp = client.chat(
            system_prompt="你是一个联想平板 PN 和 BOM 自动化项目的技术顾问。请基于会议转写内容，精确回答流程问题。不要猜测，只基于会议文本。",
            user_prompt=chunk + "\n\n---\n\n" + question,
        )
        elapsed = time.time() - t0
        results.append(resp)
        print(f"  ✅ 完成 ({elapsed:.0f}s, {len(resp)} 字符)")
    except Exception as e:
        print(f"  ❌ 失败: {e}")
        results.append(f"[分析失败: {e}]")

# 合并结果
final = "\n\n---\n\n".join(results)
out = PROJECT / "output" / "meeting_analysis.md"
out.parent.mkdir(exist_ok=True)
out.write_text(final, encoding="utf-8")

# 同时复制到知识库
kb_out = Path(r"D:\knowledge\newKnowledge\项目0713\会议分析结果.md")
kb_out.parent.mkdir(parents=True, exist_ok=True)
kb_out.write_text(final, encoding="utf-8")

print(f"\n{'='*50}")
print(f"✅ 分析完成！")
print(f"   {out}")
print(f"   {kb_out}")
print(f"   总结果: {len(final)} 字符")
