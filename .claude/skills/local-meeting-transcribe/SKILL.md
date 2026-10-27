---
name: "local-meeting-transcribe"
description: >
  本地会议录音转写流水线（保密优先，数据不出本机）：faster-whisper 转写 + ECAPA 声纹
  说话人分离 + GLM 会议纪要（全量分钟溯源）+ 标准化存档（原录音/transcript.md/minutes.md）。
  当用户提供本地会议录音文件请求转写、要求多人分角色标注、需要会议纪要/共识/行动项、
  或本流水线报错时使用。
  不用于：小宇宙播客链接分析（用 audio-mind-pipeline）、云端 ASR 配置调试。
version: "1.0.0"
author: "audio-mind 本地化实践（2026-10-26 会议实战沉淀）"
tags: ["meeting", "local-transcription", "whisper", "speechbrain", "diarization",
       "minutes", "GLM", "confidential", "windows", "troubleshooting"]
arguments_schema:
  type: "object"
  properties:
    audio_files:
      type: "array"
      items: { type: "string" }
      description: "本地录音文件路径（支持 m4a/mp3/wav/flac 等）"
    meeting_names:
      type: "array"
      items: { type: "string" }
      description: "每个录音对应的会议名称（用于纪要标题与存档目录）"
    archive_dir:
      type: "string"
      description: "存档根目录，默认 D:/PI/project/会议存档"
  required: ["audio_files"]
---

# 本地会议转写流水线（保密优先）

## Role & Objective

你是会议转写运维 Agent。目标：把本地录音转成**可溯源的存档三件套**，一次跑通：

```
录音 → ①本地转写(带时间戳) → ②声纹聚类分角色 → ③transcript.md(角色+[MM:SS])
     → ④GLM 会议纪要(分钟溯源+反编造校验) → ⑤存档(原录音格式不变)
```

项目路径：`D:/PI/project/audio-mind`（脚本、venv、模型都在此）。
核心原则：**数据不出本机**（除非用户明确确认公司允许云端转写）。

## 交付物标准（用户明确要求，不得简化）

每个录音一个存档文件夹，包含：
1. **原录音文件**——格式不变，直接复制
2. **transcript.md**——转写稿：按角色标注（说话人N）+ **每段话后 `[MM:SS]` 实际分钟标注**（需求/逻辑/共识溯源用）
3. **minutes.md**——会议纪要：共识/业务逻辑（含基于哪些表）/行动项/未决问题，**每条结论必须带 `[MM:SS]` 溯源**，禁止编造

存档目录结构：
```
{archive_dir}/{序号}_{会议名}/
├── 原录音.m4a（格式不变）
├── transcript.md
└── minutes.md
```

## 流水线架构

| 阶段 | 技术 | 脚本 | 产出 |
|------|------|------|------|
| ① 转写 | faster-whisper small/int8/beam1 + Silero VAD | `scripts/local_meeting_pipeline.py` Stage1 | 带 start/end 的片段 |
| ② 声纹嵌入 | speechbrain ECAPA-TDNN（192维向量） | 同上 Stage2 | 每窗口向量 |
| ③ 聚类对齐 | sklearn 层次聚类(余弦,阈值0.72) + 重叠投票 + 平滑 | 同上 Stage3/4 | segments.json |
| ④ 转写稿 | 模板渲染 | `scripts/gen_transcript_md.py` | transcript.md |
| ⑤ 纪要 | GLM-4.5(思考关闭) + `prompts/meeting_minutes.yaml` | `scripts/gen_minutes.py` | minutes.md |

**标准执行命令**（工作目录 = 项目根；一律用 `.venv/Scripts/python.exe` 直调，见坑 P1）：

```bash
cd D:/PI/project/audio-mind
# 转写+分角色（后台跑，日志轮询）
{ PYTHONIOENCODING=utf-8 nohup .venv/Scripts/python.exe scripts/local_meeting_pipeline.py \
    "<音频路径>" output/<任务名>/segments.json > output/<任务名>/pipeline.log 2>&1 & disown; }
# 转写稿
.venv/Scripts/python.exe scripts/gen_transcript_md.py output/<任务名>/segments.json "<存档>/transcript.md"
# 纪要（ZAI_API_KEY 取自环境变量）
.venv/Scripts/python.exe scripts/gen_minutes.py output/<任务名>/segments.json "<存档>/minutes.md" "<会议名>"
```

## 质量门（跑完必查）

1. **说话人合理性**：向用户汇报人数与发言占比；若与实际不符（如 98%/2% 但实际多人主导）→ 调低 `DIST_THRESHOLD`（0.72→0.65）只重跑 Stage 2-4（转写不用重跑，断点在）
2. **反编造校验**：gen_minutes.py 自动提取输出中所有 `[MM:SS]`，超音频时长即告警；抽查 2-3 个时间点在 transcript.md 中 grep 得到
3. **转写稿完整性**：segments.json 片段数 > 0；transcript.md 大小 > 10KB（38分钟会约 29KB）
4. **角色不猜名**：一律"说话人N"，真名映射必须由用户/参会人确认

## 环境一次性安装（已装好则跳过）

```bash
cd D:/PI/project/audio-mind
uv venv --python 3.11 && export UV_LINK_MODE=copy && uv sync
uv pip install speechbrain scikit-learn
# av 必须是 18.x（<19；uv sync 默认解析的 18.1.0 可用，验证：）
.venv/Scripts/python.exe -c "import av; assert av.__version__.startswith('18'), av.__version__"
# ECAPA 模型本地化（绕过 Windows 符号链接权限，见坑 P5）：
#   pretrained_models/spkrec-ecapa-voxceleb/ 下需有：hyperparams.yaml,
#   embedding_model.ckpt(80M), mean_var_norm_emb.ckpt, classifier.ckpt,
#   label_encoder.ckpt 与 label_encoder.txt（两个名字都要！）
```

## 踩坑清单（P1~P12，按发生顺序）

### P1. `uv run` 会同步/裁剪 venv，手动装的包会消失
**症状**：`uv pip install` 装的 speechbrain 突然 import 失败；av 版本被锁文件顶回去。
**根因**：`uv run` 默认按 uv.lock 精确同步环境（exact sync）。
**规矩**：**运行与安装一律 `.venv/Scripts/python.exe` 直调 + `uv pip install`，禁用 `uv run`**。

### P2. Python 3.13/3.14 下 av/torch 无预编译轮子，源码编译必挂
**症状**：`Building av==14.4.0` 卡死或失败；源码编译 PyAV 在 Windows 需要 ffmpeg 开发库。
**根因**：新版 Python 无 cp313/cp314 旧版 av 轮子；av≥19 删了 faster-whisper 用的 `metadata_errors` 参数（`av.open()` 报 TypeError）。
**规矩**：**venv 固定 Python 3.11**（`uv venv --python 3.11`），av 用 uv.lock 解析的 18.1.0（18.x 保留 metadata_errors 且有 cp311 轮子）。

### P3. torch 半截安装损坏（`module 'torch' has no attribute '__version__'`）
**根因**：uv 硬链接跨盘回退 copy 时中断，site-packages 里留下残缺 torch。
**修复**：`uv pip uninstall torch` + 手动删 `.venv/Lib/site-packages/torch*` + `uv pip install --link-mode=copy torch --index-url https://download.pytorch.org/whl/cpu` 重装（约 4 分钟）。

### P4. HuggingFace 下载：直连不通 + Xet 协议 401
**症状 A**：模型下载超时/失败 → 国内直连 huggingface.co 不通。
**规矩 A**：环境变量 `HF_ENDPOINT=https://hf-mirror.com`（必须在 import 前设置，脚本里已 setdefault）。
**症状 B**：`RuntimeError: Task error: ... cas-server.xethub.hf.co ... 401` → hf_xet 的 CAS 协议绕过镜像直连官方。
**规矩 B**：`HF_HUB_DISABLE_XET=1` + `uv pip uninstall hf_xet`（脚本已 setdefault，venv 里已卸）。

### P5. Windows 符号链接无权限（WinError 1314），speechbrain 拉模型必崩
**症状**：`OSError: [WinError 1314] 客户端没有所需的特权` at `pathlib.symlink_to`，来源 speechbrain `fetching.py`。
**根因**：未开 Windows 开发者模式，os.symlink 无特权；speechbrain Pretrainer 强制 symlink 收集。
**修复**：把模型文件**手动下载到 `pretrained_models/spkrec-ecapa-voxceleb/`**（走镜像 `/resolve/main/<file>`），文件清单见"环境一次性安装"。
**隐藏细节**：hyperparams.yaml 的 paths 里 label_encoder 写的是 `label_encoder.txt`，但 CategoricalEncoder 加载时要求 **`label_encoder.ckpt`** —— 两个文件名都要存在，缺一个就触发重新 fetch → 又崩 symlink。

### P6. faster-whisper 1.2 的 decode_audio 没有 `mono` 参数
**症状**：`TypeError: decode_audio() got an unexpected keyword argument 'mono'`。
**规矩**：`decode_audio(path, sampling_rate=16000)` 即可，默认混单声道。当前脚本已修。

### P7. 本机 CPU 跑 medium 模型只有 0.7x 实时（38分钟音频≈1小时+）
**实测数据**（8核，含超线程）：medium+beam5+词级时间戳 ≈ 0.7x 实时；small+beam1+无词级 ≈ **2.4x 实时**。
**规矩**：`WHISPER_MODEL="small"`、`BEAM_SIZE=1`、不开 `word_timestamps`（片段级时间戳已满足分钟溯源）。三档质量-速度取舍按此基准估算，**长音频开跑前必须告知用户预估耗时**。

### P8. ECAPA 窗口数爆炸（1476 个 → 6 分钟变 40 分钟）
**规矩**：声纹窗口必须**先合并相邻片段（间隙≤1.5s）成语音块再切 ≤12s 窗口**（38分钟会 ≈195 窗口，~6分钟）。脚本 `_make_chunks()` 已实现。

### P9. 无断点存档 = 崩溃重跑 30 分钟转写
**规矩**：Stage 1 完成立即写 `segments_raw.json` 断点；重跑时检测断点直接跳过转写。当前脚本已实现（输出目录下 `<名>_raw.json`）。**给流水线加任何新阶段都要遵守"每阶段落盘"**。

### P10. Git Bash 后台启动的两个坑
**坑 A**：`cd X && cmd & disown` 的 `&` 会把**整条 `cd &&` 链**丢进后台子 shell，前台 CWD 不变——检查要用**绝对路径**。
**坑 B**：同一条启动命令跑两次 = 双进程抢 CPU + 日志互相覆盖（症状：日志只剩一行、速度减半）。
**规矩**：启动前先 `tasklist | grep -i python` 确认无 >500MB 的残留进程；用 `{ ...nohup... & disown; }` 包裹；日志路径用绝对路径；启动后 sleep 几秒用 tasklist 验证**只有一个**大进程。

### P11. GLM-4.5 推理模式烧光 max_tokens 输出空内容
**症状**：`输出 0 字符, tokens=15195`，finish_reason=length——token 全花在 reasoning_content。
**规矩**：glm-4.5 系列调用必须加 `extra_body={"thinking": {"type": "disabled"}}`（纪要属文档抽取任务，关思考不影响质量）+ `max_tokens=16384`。脚本已实现，失败自动降级 glm-4-flash。

### P12. 云端转写（火山/阿里云）的合规红线
- URL 模式（audio-mind 现有代码）= 录音要传第三方对象存储 + 生成可访问 URL，保密风险最大
- 火山也有**二进制直传**（极速版/SAUC WebSocket），无第三方副本无 URL，但数据仍离开本机
- **任何云端路径必须用户明确确认公司允许后才可走**；默认一律本地方案
- `volcengine.py` 已打好会议模式补丁（`show_utterances: true` + `ssd_version: "300"` 长音频会议版说话人分离），settings.yaml 里 `ssd_version: "300"` 当前启用，走云端时生效

## 性能基准（本机 8 核实测，38分45秒会议）

| 阶段 | 耗时 | 说明 |
|------|------|------|
| Stage1 转写 | ~17 min（2.4x 实时） | small/int8/beam1/VAD |
| Stage2 声纹 | ~6 min（195 窗口） | ECAPA CPU |
| Stage3+4 聚类对齐 | <2 s | sklearn |
| 纪要生成 | ~1 min | GLM-4.5（思考关闭），9724 tokens |
| **合计** | **~25 min / 38min 音频** | 推算 67min 音频 ≈ 45 min |

## Output Format

每个录音完成后输出结构化报告：

```
## ✅ 会议转写完成：<会议名>

| 项 | 值 |
|----|-----|
| 音频 | <时长> / <大小> |
| 说话人 | N 人（发言占比 …）⚠️ 需用户确认 |
| 片段 | N 段（合并后） |
| 纪要溯源 | M 处 [MM:SS]，反编造校验超界 K 处 |
| 存档 | <archive_dir>/<序号>_<会议名>/（三件套） |
```

## Constraints & Safety

- **默认全本地**；云端方案只在用户明确确认合规后使用（P12）
- **禁止猜测说话人真名**，标签一律"说话人N"
- **纪要禁止编造**：每条结论必须可溯源到 `[MM:SS]`；转写稿没有的内容写"未提及"
- 转写中的 ASR 错字不擅自"更正"，纪要里存疑术语标`（音，待核实）`
- 后台任务必须验证单进程（P10），长音频开跑前告知预估耗时（P7）
- `.env` 与密钥永不写入仓库；纪要引用的用户业务数据不外发（GLM 调用前需用户已认可文本出本机）
