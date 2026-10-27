# -*- coding: utf-8 -*-
"""本地会议转写流水线（数据全程不出本机）

Stage 1: faster-whisper (medium/int8/CPU) 带词级时间戳转写
Stage 2: speechbrain ECAPA 声纹嵌入（按转写片段及长片段子窗口提取）
Stage 3: 层次聚类（余弦距离阈值）划分说话人 → 说话人1..N
Stage 4: 片段-说话人对齐（重叠时长加权投票）+ 孤立段平滑

输出 JSON:
{
  "audio": 文件名, "duration": 总秒数, "n_speakers": 人数,
  "speaker_talk": {"1": 说话秒数, ...},
  "segments": [{"start": 秒, "end": 秒, "speaker": "1", "text": "..."}]
}

用法:
  uv run python scripts/local_meeting_pipeline.py <audio> <out_json>
"""

import json
import os
import sys
import time
from pathlib import Path

# HuggingFace 直连不通时自动走国内镜像（必须在 import 前设置）
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")  # xet 协议绕过镜像直连会 401，强制走普通 HTTP

import numpy as np
import torch
from faster_whisper import WhisperModel
from faster_whisper.audio import decode_audio
from sklearn.cluster import AgglomerativeClustering
from speechbrain.inference.speaker import EncoderClassifier

# ── 可调参数 ──────────────────────────────────────────
WHISPER_MODEL = "small"         # 实测本机 CPU 跑 medium 仅 0.7x 实时（总耗时≈3h），small 快 2~2.5 倍
COMPUTE_TYPE = "int8"           # CPU 量化加速
CPU_THREADS = 8
BEAM_SIZE = 1                   # beam=1（贪心）换 ~2x 速度，会议转写质量可接受
MAX_CHUNK_S = 12.0              # 声纹嵌入子窗口上限（秒）
MIN_CHUNK_S = 0.8               # 过短窗口不嵌入（声纹特征不稳定）
DIST_THRESHOLD = 0.72           # 层次聚类余弦距离阈值（小→易合并，大→易分裂）
MERGE_GAP_S = 1.2               # JSON 输出时同说话人相邻片段合并的最大间隔
SMOOTH_PASSES = 3               # 孤立说话人段平滑迭代次数
INITIAL_PROMPT = "以下是项目需求会议的录音转写，涉及业务需求、数据表、系统逻辑的讨论。"


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ── Stage 1: 转写 ─────────────────────────────────────
def stage1_transcribe(audio_path: str):
    log(f"Stage 1/4: faster-whisper 转写开始 (model={WHISPER_MODEL}, {COMPUTE_TYPE}, {CPU_THREADS}线程)")
    t0 = time.time()
    model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type=COMPUTE_TYPE,
                         cpu_threads=CPU_THREADS, local_files_only=False)
    segments_iter, info = model.transcribe(
        audio_path,
        language="zh",
        beam_size=BEAM_SIZE,
        vad_filter=True,
        condition_on_previous_text=True,
        initial_prompt=INITIAL_PROMPT,
    )
    raw = []
    for seg in segments_iter:  # 生成器，边转边收
        text = seg.text.strip()
        if text:
            raw.append({"start": float(seg.start), "end": float(seg.end), "text": text})
        if len(raw) % 10 == 0:
            pct = seg.end / info.duration * 100 if info.duration else 0
            log(f"  转写进度: {seg.end:.0f}s / {info.duration:.0f}s ({pct:.0f}%), 片段数={len(raw)}")
    log(f"Stage 1/4 完成: {len(raw)} 个片段, 耗时 {time.time()-t0:.0f}s")
    return raw, float(info.duration)


# ── Stage 2: 声纹嵌入 ─────────────────────────────────
def _make_chunks(raw):
    """相邻片段合并成语音块（间隙≤1.5s）再切 ≤MAX_CHUNK_S 窗口，大幅减少窗口数"""
    blocks = []
    for seg in raw:
        if blocks and seg["start"] - blocks[-1][1] <= 1.5:
            blocks[-1][1] = max(blocks[-1][1], seg["end"])
        else:
            blocks.append([seg["start"], seg["end"]])
    chunks = []
    for s, e in blocks:
        dur = e - s
        if dur < MIN_CHUNK_S:
            continue
        pos = s
        while pos < e - 1e-6:
            win_end = min(pos + MAX_CHUNK_S, e)
            # 若剩余尾巴过短，并入上一窗（回退窗口起点）
            if e - win_end < MIN_CHUNK_S:
                win_end = e
            chunks.append((pos, win_end))
            pos = win_end
    return chunks


def stage2_embed(audio_path: str, chunks):
    log(f"Stage 2/4: ECAPA 声纹嵌入开始 ({len(chunks)} 个窗口)")
    t0 = time.time()
    audio = decode_audio(audio_path, sampling_rate=16000)  # 默认混为单声道
    encoder = EncoderClassifier.from_hparams(
        source="speechbrain/spkrec-ecapa-voxceleb",
        savedir=str(Path(__file__).parent.parent / "pretrained_models" / "spkrec-ecapa-voxceleb"),
        run_opts={"device": "cpu"},
    )
    embs = []
    for i, (s, e) in enumerate(chunks):
        w = audio[int(s * 16000):int(e * 16000)]
        if len(w) < int(MIN_CHUNK_S * 16000):
            w = np.pad(w, (0, int(MIN_CHUNK_S * 16000) - len(w)))
        tensor = torch.from_numpy(np.ascontiguousarray(w)).float().unsqueeze(0)
        with torch.no_grad():
            emb = encoder.encode_batch(tensor).squeeze().cpu().numpy()
        embs.append(emb / (np.linalg.norm(emb) + 1e-9))  # L2 归一化
        if (i + 1) % 50 == 0:
            log(f"  嵌入进度: {i+1}/{len(chunks)}")
    log(f"Stage 2/4 完成: 耗时 {time.time()-t0:.0f}s")
    return np.array(embs)


# ── Stage 3: 聚类 ─────────────────────────────────────
def stage3_cluster(embs):
    log("Stage 3/4: 层次聚类划分说话人")
    if len(embs) == 0:
        return []
    if len(embs) == 1:
        return [0]
    cl = AgglomerativeClustering(
        n_clusters=None,
        distance_threshold=DIST_THRESHOLD,
        metric="cosine",
        linkage="average",
    )
    labels = cl.fit_predict(embs)
    log(f"  聚出 {labels.max()+1} 个声纹簇")
    return labels.tolist()


# ── Stage 4: 对齐 + 平滑 ──────────────────────────────
def stage4_align(raw, chunks, labels):
    log("Stage 4/4: 片段-说话人对齐")
    chunk_spk = [(s, e, lab) for (s, e), lab in zip(chunks, labels)]

    def assign(seg):
        """重叠时长加权投票"""
        votes = {}
        for s, e, lab in chunk_spk:
            ov = min(seg["end"], e) - max(seg["start"], s)
            if ov > 0:
                votes[lab] = votes.get(lab, 0.0) + ov
        if not votes:
            return None
        return max(votes, key=votes.get)

    for seg in raw:
        seg["spk"] = assign(seg)

    # 无投票片段（罕见）：取时间上最近的有标签片段
    labeled = [s for s in raw if s["spk"] is not None]
    for seg in raw:
        if seg["spk"] is None and labeled:
            seg["spk"] = min(labeled, key=lambda s: min(abs(s["start"]-seg["start"]), abs(s["end"]-seg["end"])))["spk"]

    # 孤立段平滑：两侧同说话人夹住的不同段 → 归入两侧
    for _ in range(SMOOTH_PASSES):
        changed = False
        for i in range(1, len(raw) - 1):
            if raw[i]["spk"] != raw[i-1]["spk"] and raw[i]["spk"] == raw[i+1]["spk"] and raw[i-1]["spk"] != raw[i+1]["spk"]:
                raw[i]["spk"] = raw[i+1]["spk"]; changed = True
            elif raw[i]["spk"] != raw[i+1]["spk"] and raw[i]["spk"] == raw[i-1]["spk"] and raw[i-1]["spk"] != raw[i+1]["spk"]:
                raw[i]["spk"] = raw[i-1]["spk"]; changed = True
            elif raw[i-1]["spk"] == raw[i+1]["spk"] and raw[i]["spk"] != raw[i-1]["spk"]:
                raw[i]["spk"] = raw[i-1]["spk"]; changed = True
        if not changed:
            break

    # 簇编号 → 说话人1..N（按首次出现顺序）
    order = []
    for seg in raw:
        if seg["spk"] not in order:
            order.append(seg["spk"])
    remap = {old: str(i + 1) for i, old in enumerate(order)}
    for seg in raw:
        seg["speaker"] = remap[seg["spk"]]

    # 同说话人相邻且间隔小 → 合并
    merged = []
    for seg in raw:
        if merged and seg["speaker"] == merged[-1]["speaker"] and seg["start"] - merged[-1]["end"] <= MERGE_GAP_S:
            merged[-1]["end"] = seg["end"]
            merged[-1]["text"] += seg["text"]
        else:
            merged.append(dict(seg))
    return merged


def main():
    if len(sys.argv) < 3:
        print("用法: uv run python scripts/local_meeting_pipeline.py <audio> <out_json>")
        sys.exit(1)
    audio_path, out_json = sys.argv[1], sys.argv[2]
    total_t0 = time.time()

    # 断点恢复：转写结果已存档则跳过 Stage 1（后续阶段崩溃不必重跑转写）
    raw_ckpt = Path(out_json).parent / (Path(out_json).stem + "_raw.json")
    if raw_ckpt.exists():
        log(f"发现转写断点 {raw_ckpt}，跳过 Stage 1")
        ck = json.loads(raw_ckpt.read_text(encoding="utf-8"))
        raw, duration = ck["segments"], ck["duration"]
    else:
        raw, duration = stage1_transcribe(audio_path)
        if not raw:
            print(json.dumps({"error": "no speech detected"}, ensure_ascii=False))
            sys.exit(2)
        raw_ckpt.parent.mkdir(parents=True, exist_ok=True)
        raw_ckpt.write_text(json.dumps(
            {"audio": Path(audio_path).name, "duration": duration, "segments": raw},
            ensure_ascii=False), encoding="utf-8")
        log(f"转写结果已存档: {raw_ckpt}")

    chunks = _make_chunks(raw)
    embs = stage2_embed(audio_path, chunks)
    labels = stage3_cluster(embs)
    merged = stage4_align(raw, chunks, labels)

    talk = {}
    for seg in merged:
        talk[seg["speaker"]] = talk.get(seg["speaker"], 0.0) + (seg["end"] - seg["start"])

    result = {
        "audio": Path(audio_path).name,
        "duration": duration,
        "n_speakers": len(talk),
        "speaker_talk": {k: round(v, 1) for k, v in sorted(talk.items(), key=lambda x: int(x[0]))},
        "segments": [
            {"start": round(s["start"], 2), "end": round(s["end"], 2),
             "speaker": s["speaker"], "text": s["text"]}
            for s in merged
        ],
    }
    Path(out_json).parent.mkdir(parents=True, exist_ok=True)
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)

    log(f"全部完成! 说话人数={result['n_speakers']}, 发言占比={result['speaker_talk']}, "
        f"总耗时 {time.time()-total_t0:.0f}s → {out_json}")


if __name__ == "__main__":
    main()
