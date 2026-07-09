# audio-mind 🎧

自动播客洞察 Agent：粘贴小宇宙播客链接 → 自动下载音频 → Whisper 转写 → DeepSeek 基于用户画像提取个性化洞察。

## 架构概述

项目分为三阶段 Pipeline：**下载 → 转写 → 分析**。下载阶段从小宇宙 SSR 页面的 `og:audio` 标签提取 CDN 音频链接（阿里云 OSS，无需鉴权），同时从 JSON-LD 提取完整元数据；转写阶段使用本地 `faster-whisper large-v3` 进行中文语音识别，支持 VAD 静音过滤；分析阶段将转写文本与用户画像（持久化在 CLAUDE.md 中）一起送入 DeepSeek API，生成包含核心观点、行动项、关键引述等六部分的个性化洞察文档。所有产出物保存为 Markdown 文件，存储在 `output/{播客名}_{期号}_{主题}/` 目录下。

## 快速开始

### 1. 环境准备

```bash
# 安装依赖（uv 会自动管理 Python 版本）
uv sync

# 配置 DeepSeek API Key
cp .env.example .env
# 编辑 .env，填入你的 DEEPSEEK_API_KEY
```

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
```
