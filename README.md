# audio-mind 🎧

自动播客洞察 Agent：粘贴小宇宙播客链接 → 自动下载音频 → Whisper 转写 → DeepSeek 基于用户画像提取个性化洞察。

## 架构概述

项目分为三阶段 Pipeline：**下载 → 转写 → 分析**。下载阶段从小宇宙 SSR 页面的 `og:audio` 标签提取 CDN 音频链接（阿里云 OSS，无需鉴权），同时从 JSON-LD 提取完整元数据；转写阶段使用本地 `faster-whisper large-v3` 进行中文语音识别，支持 VAD 静音过滤；分析阶段将转写文本与用户画像（持久化在 CLAUDE.md 中）一起送入 DeepSeek API，生成包含核心观点、行动项、关键引述等六部分的个性化洞察文档。所有产出物保存为 Markdown 文件，存储在 `output/{播客名}_{期号}_{主题}/` 目录下。

## 快速开始

### 1. 环境准备

```bash
# 安装依赖（uv 会自动管理 Python 版本）
uv sync

# 配置 API 密钥（转写/分析必需）
cp .env.example .env
# 编辑 .env，填入你的 API Key（来源见下方「API 密钥获取」）
```

**⚠️ 安全提示**：`.env` 已被 `.gitignore` 排除，**切勿把真实 Key 写入任何会被提交的文件**（README、代码、示例配置都不行）。Key 只在本地 `.env` 中维护。

### API 密钥获取（Key 来源）

| 服务 | 用途 | 获取方式 |
|------|------|---------|
| **火山引擎**（默认转写引擎） | 语音转写（豆包语音识别大模型） | [火山引擎语音技术控制台](https://console.volcengine.com/speech/app) → 旧版控制台 → 创建应用 → 勾选「录音文件识别大模型 → 录音文件识别大模型极速版」→ 复制 **APP ID** 和 **Access Token**，填入 `VOLCENGINE_APP_ID` / `VOLCENGINE_ACCESS_TOKEN` |
| **阿里云**（备用转写引擎） | 语音转写（智能语音交互 NLS） | [阿里云 RAM 访问控制](https://ram.console.aliyun.com/users) → 创建 RAM 用户 → 勾选「OpenAPI 调用访问」→ 授权 `AliyunNLSFullAccess` + `AliyunOSSFullAccess` → 复制 **AccessKey ID** / **AccessKey Secret**，填入 `ALIBABA_ACCESS_KEY_ID` / `ALIBABA_ACCESS_KEY_SECRET` |
| **DeepSeek**（分析阶段） | 个性化洞察生成 | [DeepSeek 开放平台](https://platform.deepseek.com) → API Keys → 创建 Key，填入 `DEEPSEEK_API_KEY` |

> 转写引擎切换：编辑 `config/settings.yaml` 中 `transcriber.provider` 为 `volcengine`（默认）/ `alibaba` / `whisper`（本地，无需 Key 但 CPU 极慢）。

**前置条件**：需要安装 ffmpeg（pydub 音频处理依赖）
- macOS: `brew install ffmpeg`
- Windows: `choco install ffmpeg` 或从 https://ffmpeg.org/download.html 下载

### 2. 在 Claude Code 中使用（推荐）

在 VSCode 中打开本项目，对 Claude Code 说：

```
分析这个播客 https://www.xiaoyuzhoufm.com/episode/xxxxx
```

首次使用时 Agent 会引导你填写用户画像（10 项），之后永久存储。

### 3. CLI 使用

```bash
uv run python -m src.pipeline --url https://www.xiaoyuzhoufm.com/episode/xxxxx
```

### 4. 运行测试

```bash
uv run pytest
```

## 会议转写模式（本地，保密优先）🎧

针对**公司内部会议录音**的离线转写模式：录音不出本机，多人声纹分角色，产出可分钟级溯源的存档三件套。

```bash
# 转写 + 声纹分角色（后台跑）
.venv/Scripts/python.exe scripts/local_meeting_pipeline.py "会议录音.m4a" output/mt01/segments.json

# 生成转写稿（角色 + [MM:SS] 分钟标注）
.venv/Scripts/python.exe scripts/gen_transcript_md.py output/mt01/segments.json 存档/transcript.md

# 生成会议纪要（GLM，全量分钟溯源 + 反编造校验，需 ZAI_API_KEY 环境变量）
.venv/Scripts/python.exe scripts/gen_minutes.py output/mt01/segments.json 存档/minutes.md "会议名"
```

- 适用场景：内部会议纪要、共识/行动项梳理、需求溯源；**云端 ASR（火山/阿里云）需先确认公司允许数据出本机**
- 完整流程、性能基准与 12 条踩坑清单见 `.claude/skills/local-meeting-transcribe/SKILL.md`
- 依赖：venv 需 Python 3.11 + `speechbrain` `scikit-learn`（安装步骤见 SKILL.md）

## 技术选型理由

| 组件 | 选择 | 理由 |
|------|------|------|
| 音频下载 | `requests` + `BeautifulSoup4` | 小宇宙为 SSR 渲染，og:audio 含 CDN 音频链接（阿里云 OSS，无需鉴权），JSON-LD 含完整元数据 |
| 语音转写 | `faster-whisper large-v3` | 本地免费运行，中文准确率高，VAD 静音过滤节省算力 |
| LLM 分析 | **DeepSeek API** | ¥1/百万 token（性价比极高），128K 上下文，OpenAI 兼容接口，中文出色 |
| 包管理 | `uv` | 速度快，Python 版本管理，pyproject.toml 统一配置 |

## 输出结构

```
output/知行小酒馆_E235_AI改变你/
├── transcript.md    # 完整转写（含 [HH:MM:SS] 时间戳）
└── insights.md      # 个性化洞察（6 部分）
```

## 用户画像

首次使用时 Agent 会通过 10 项引导问题采集详细画像，存储在 `CLAUDE.md` 的 `## User Persona` 段。后续使用自动读取。如需修改，直接编辑该段或删除后重新对话。

## 项目结构

```
src/
├── pipeline.py          # 核心编排
├── exceptions.py        # 自定义异常
├── downloader/          # 小宇宙 + RSS
├── transcriber/         # faster-whisper
├── analyzer/            # DeepSeek + 分段
├── models/              # Pydantic 数据模型
└── utils/               # 配置/日志/HTTP/画像/文档生成
scripts/
├── local_meeting_pipeline.py  # 本地会议转写+声纹分角色（保密优先）
├── gen_transcript_md.py       # segments.json → transcript.md
├── gen_minutes.py             # segments.json → minutes.md（GLM）
└── fact_check.py              # 事实核查（Tavily+LLM）
.claude/skills/
├── audio-mind-pipeline/       # 播客 Pipeline 运维 skill
└── local-meeting-transcribe/  # 本地会议转写 skill（含踩坑清单）
```
