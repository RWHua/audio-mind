# -*- coding: utf-8 -*-
"""segments.json → minutes.md（会议纪要，GLM 分析，全量分钟溯源）

流程:
1. 从 segments.json 重建带 [MM:SS] 时间戳的转写正文
2. 加载 prompts/meeting_minutes.yaml 模板
3. 调用 GLM（OpenAI 兼容接口，密钥取环境变量 ZAI_API_KEY）
4. 反编造校验: 提取输出中所有 [MM:SS]，超出音频时长的时间点会被标记警告
5. 保存 minutes.md

用法: python scripts/gen_minutes.py <segments.json> <out_minutes.md> <会议名称>
"""
import json
import os
import re
import sys
from pathlib import Path

import yaml
from openai import OpenAI

BASE = Path(__file__).parent.parent
MODELS = ["glm-4.5", "glm-4-flash"]  # 依次尝试，取第一个可用的


def fmt_ts(sec: float) -> str:
    m, s = divmod(int(round(sec)), 60)
    return f"{m:02d}:{s:02d}"


def build_transcript_text(segs) -> str:
    lines = []
    for seg in segs:
        text = seg.get("text", "").strip()
        if text:
            lines.append(f"说话人{seg.get('speaker', '?')}：{text} [{fmt_ts(seg['start'])}]")
    return "\n".join(lines)


def validate_timestamps(md: str, duration: float):
    """反编造校验：所有 [MM:SS] 必须落在音频时长内"""
    stamps = re.findall(r"\[(\d{1,3}):(\d{2})\]", md)
    total, invalid = 0, []
    for m, s in stamps:
        t = int(m) * 60 + int(s)
        total += 1
        if t > duration + 5:
            invalid.append(f"[{m}:{s}]")
    return total, invalid


def main():
    if len(sys.argv) < 4:
        print("用法: python scripts/gen_minutes.py <segments.json> <out.md> <会议名称>")
        sys.exit(1)
    seg_path, out_path, meeting_name = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]

    data = json.loads(seg_path.read_text(encoding="utf-8"))
    duration = data.get("duration", 0)
    transcript = build_transcript_text(data.get("segments", []))
    print(f"转写稿: {len(transcript)} 字符, 时长 {fmt_ts(duration)}")

    tpl = yaml.safe_load((BASE / "prompts" / "meeting_minutes.yaml").read_text(encoding="utf-8"))
    system = tpl["system"]
    user = (tpl["user"]
            .replace("{{meeting_name}}", meeting_name)
            .replace("{{duration}}", fmt_ts(duration))
            .replace("{{transcript}}", transcript))

    api_key = os.environ.get("ZAI_API_KEY", "")
    if not api_key:
        print("错误: 未找到 ZAI_API_KEY 环境变量")
        sys.exit(1)
    client = OpenAI(api_key=api_key, base_url="https://open.bigmodel.cn/api/paas/v4", timeout=300)

    content, used = None, None
    for model in MODELS:
        try:
            print(f"调用 {model} 生成会议纪要...")
            extra = {"thinking": {"type": "disabled"}} if model.startswith("glm-4.5") else None
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": user}],
                max_tokens=16384,
                temperature=0.3,
                extra_body=extra,
            )
            content = resp.choices[0].message.content or ""
            used = model
            print(f"OK: {model}, 输出 {len(content)} 字符, tokens={resp.usage.total_tokens}")
            break
        except Exception as e:
            print(f"  {model} 失败: {e}")
    if not content:
        print("错误: 所有模型均调用失败")
        sys.exit(2)

    n_ts, invalid = validate_timestamps(content, duration)
    warn = ""
    if invalid:
        warn = ("\n\n> ⚠️ **反编造校验警告**：以下时间标注超出音频时长，"
                "可能是模型幻觉，引用前请核对原转写稿：" + "、".join(sorted(set(invalid))))
    print(f"时间标注校验: 共 {n_ts} 处, 超界 {len(invalid)} 处")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    header = (f"<!-- 由 audio-mind 会议纪要流水线生成 | 模型: {used} | "
              f"溯源时间点共 {n_ts} 处 -->\n\n")
    out_path.write_text(header + content + warn, encoding="utf-8")
    print(f"OK → {out_path}")


if __name__ == "__main__":
    main()
