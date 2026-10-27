# -*- coding: utf-8 -*-
"""segments.json → transcript.md（会议转写稿）

格式要求（用户指定）：
- 标清角色（说话人N，声纹聚类，不猜测真名避免胡编）
- 每段话后有实际分钟标注 [MM:SS]（该句开始时间，用于需求/逻辑/共识溯源）
- Markdown 格式

用法: python scripts/gen_transcript_md.py <segments.json> <transcript.md>
"""
import json
import sys
from pathlib import Path


def fmt_ts(sec: float) -> str:
    m, s = divmod(int(round(sec)), 60)
    return f"{m:02d}:{s:02d}"


def main():
    if len(sys.argv) < 3:
        print("用法: python scripts/gen_transcript_md.py <segments.json> <transcript.md>")
        sys.exit(1)
    seg_path, out_path = Path(sys.argv[1]), Path(sys.argv[2])
    data = json.loads(seg_path.read_text(encoding="utf-8"))

    dur = data.get("duration", 0)
    n_spk = data.get("n_speakers", 0)
    talk = data.get("speaker_talk", {})
    segs = data.get("segments", [])

    lines = []
    title = Path(data.get("audio", "会议录音")).stem
    lines.append(f"# {title} — 会议录音转写稿\n")
    lines.append(f"> 🎧 音频时长：**{fmt_ts(dur)}** ｜ 说话人：**{n_spk} 人** ｜ 语义片段：**{len(segs)} 段**")
    lines.append("> 📌 时间标注约定：每段话末尾的 `[MM:SS]` 为该句**开始时刻**（分:秒），用于需求、逻辑、共识的溯源定位。")
    lines.append("> 📌 角色说明：由声纹聚类自动区分（说话人1~N），**真实姓名未经参会人确认，请勿臆测对应关系**。\n")

    if talk:
        lines.append("## 发言时长统计\n")
        lines.append("| 说话人 | 发言时长 | 占比 |")
        lines.append("|--------|---------|------|")
        total_talk = sum(talk.values()) or 1
        for sid, sec in sorted(talk.items(), key=lambda x: int(x[0])):
            lines.append(f"| 说话人{sid} | {fmt_ts(sec)} | {sec/total_talk*100:.0f}% |")
        lines.append("")

    lines.append("## 转写正文\n")
    for seg in segs:
        spk = seg.get("speaker", "?")
        text = seg.get("text", "").strip()
        if not text:
            continue
        lines.append(f"**说话人{spk}**：{text} `[{fmt_ts(seg['start'])}]`\n")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"OK → {out_path} ({len(lines)} 行)")


if __name__ == "__main__":
    main()
