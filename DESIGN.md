# Podcast Insight Agent（audio-mind）— 产品与技术设计文档

> **版本**：v5 · **日期**：2026-06-29 · **状态**：设计完成，待实施

---

## 1. 产品概述

### 1.1 一句话描述

在 VSCode 的 Claude Code 对话中粘贴播客链接，Agent 自动完成音频下载、语音转写、内容分析，产出基于你个人画像的个性化洞察文档。

### 1.2 核心用户故事

> 我在 VSCode 里打开 audio-mind 项目，对 Claude Code 说：「分析这个播客 https://www.xiaoyuzhoufm.com/episode/xxxxx」。首次使用时代理会逐项引导我填写画像问卷，之后永久存储。几分钟后，`output/` 下出现一个以播客主题命名的文件夹，里面是完整转写和个性化洞察。

### 1.3 交互方式

```
首次使用：
  用户  →  粘贴播客链接
  Agent →  展示 10 项画像引导问题
  用户  →  逐项填写
  Agent →  画像存入 CLAUDE.md → 开始分析 → 产出文档

后续使用：
  用户  →  粘贴播客链接
  Agent →  画像已加载 ✅ → 下载 → 转写 → 分析 → 产出文档
```

### 1.4 输出结构

```
output/
└── 知行小酒馆_E235_AI改变你/     ← {播客名}_{期号}_{简短主题}
    ├── transcript.md            ← 完整转写（含时间戳）
    └── insights.md              ← 个性化洞察
```

---

## 2. 技术选型与理由

| 组件 | 选择 | 理由 |
|------|------|------|
| **运行方式** | Claude Code 对话驱动，内部调用 Python 脚本 | 用户无需开终端记命令 |
| **Python** | ≥3.10 | 兼容所有依赖 |
| **包管理** | `uv` | 速度快，pyproject.toml 统一管理 |
| **音频下载** | `requests` + `BeautifulSoup4` | **已对小宇宙实际抓包验证**：SSR 渲染，og:audio 含 CDN 链接（阿里云 OSS，无需鉴权），JSON-LD 含完整元数据 |
| **语音转写** | `faster-whisper`（本地） | 免费、离线、中文 large-v3 准确率高、速度快 4x |
| **LLM 分析** | **DeepSeek API** | ¥1/百万 token · 128K 上下文 · OpenAI 兼容接口 · 中文出色 |
| **测试** | `pytest` | Python 生态最流行 |
| **配置** | `pydantic` + `pyyaml` | 类型安全配置校验 |
| **重试** | `tenacity` + `requests.Retry` | 超时 + 指数退避 |
| **存储** | 文件系统（Markdown） | 免数据库，文档直接可读 |

---

## 3. 目录结构

```
audio-mind/
├── .env                          # API 密钥（不进 Git）
├── .gitignore                    # 忽略音频/临时/output
├── pyproject.toml                # 项目配置 + 依赖
├── README.md                     # 架构说明 + 使用指南
├── DESIGN.md                     # 本文件
├── CLAUDE.md                     # 项目规范 + 用户画像（持久化）
│
├── config/
│   └── settings.yaml             # 全局设置
│
├── prompts/
│   ├── analyze.yaml              # 主分析 prompt
│   ├── summarize_chunk.yaml      # 分段摘要 prompt
│   └── synthesize.yaml           # 跨段合成 prompt
│
├── src/
│   ├── __init__.py
│   ├── pipeline.py               # 核心 Pipeline（import 即用）
│   ├── exceptions.py             # 自定义异常类
│   ├── downloader/               # 小宇宙 + RSS
│   ├── transcriber/              # faster-whisper
│   ├── analyzer/                 # DeepSeek + Chunker + Synthesizer
│   ├── models/                   # Pydantic 数据模型
│   └── utils/                    # HTTP · 配置 · Markdown · CLAUDE.md 读写 · 画像管理 · 日志
│
├── tests/                        # pytest
│
└── output/                       # 输出根目录（gitignored）
    └── {播客名}_{期号}_{主题}/    # 每期一个文件夹
        ├── transcript.md
        └── insights.md
```

---

## 4. 核心数据流

```
用户: "分析这个播客 https://xiaoyuzhoufm.com/episode/xxx"
│
├─ [预检] 读取 CLAUDE.md → 检查「## User Persona」
│   ├─ 缺失 → 展示 10 项引导问题 → 用户填写 → 存入 CLAUDE.md
│   └─ 存在 → 直接加载
│
├─ [Stage 1] Downloader
│   ├─ GET 页面 HTML（SSR，无需 JS）
│   ├─ og:audio → CDN 音频（media.xyzcdn.net · 阿里云 OSS · 无需鉴权）
│   ├─ JSON-LD → 标题 · 播客名 · 时长 · 节目笔记
│   └─ 流式下载音频
│
├─ [Stage 2] Transcriber
│   ├─ pydub → 16kHz mono WAV
│   ├─ faster-whisper large-v3 → 转写（VAD 过滤静音）
│   └─ 返回全文 + 带时间戳分段
│
└─ [Stage 3] Analyzer
    ├─ token 估算 → 超长自动分段（8000字/段 · 10%重叠）
    ├─ 画像 + 节目笔记 + 转写 → DeepSeek → 结构化洞察
    ├─ 确定文件夹名 → {播客名}_{期号}_{简短主题}
    ├─ 生成 transcript.md
    └─ 生成 insights.md
```

---

## 5. 关键设计决策

### 5.1 小宇宙抓取（已实测验证 ✅）

**实测对象**：`xiaoyuzhoufm.com/episode/6a06c4b91b7bd50295331e94`（知行小酒馆 E235 · 82分钟）

| 需要的数据 | HTML 来源 | 实测结果 |
|-----------|---------|---------|
| 音频地址 | `<meta property="og:audio">` | `media.xyzcdn.net/.../xxx.m4a` · HTTP 200 · 76MB · 阿里云 OSS CDN · 无需鉴权 |
| 标题 | `<meta property="og:title">` | "E235 与其担心 AI 改变你…" |
| 封面 | `<meta property="og:image">` | 直接可用 |
| 完整元数据 | `<script name="schema:podcast-show">`（JSON-LD） | 播客名「知行小酒馆」· 时长 PT82M · 完整节目笔记（含时间轴 + 术语解释） |

核心代码仅两行，不需要逆向工程。

### 5.2 用户画像采集（首次使用）

Agent 检测到 CLAUDE.md 中无画像时，不要求用户写小作文，而是逐项列出 **10 项引导问题**，确保画像足够详细：

| # | 问题 | 说明 |
|---|------|------|
| 1 | 你的名字（或昵称）？ | 用于分析报告中的称呼 |
| 2 | 你的职业是什么？从事多久了？ | 理解你的专业背景 |
| 3 | 你目前所在的行业/领域？ | 判断播客内容与你的相关性 |
| 4 | 你的教育背景或专业方向？ | 辅助理解你的知识基础 |
| 5 | 你目前最关注的技术/专业领域有哪些？ | 核心兴趣点，Agent 会优先提取相关内容 |
| 6 | 除专业外，你对哪些非技术领域感兴趣？ | 拓宽洞察维度 |
| 7 | 你近期的目标是什么？（6-12 个月内想达成的） | 指导行动项生成 |
| 8 | 你的长期目标是什么？（3-5 年的愿景） | 战略性洞察方向 |
| 9 | 你对内容有什么偏好？ | 风格偏好 + 关注主题词 + 认知偏见/倾向 |
| 10 | 你当前面临什么挑战或困惑？ | Agent 会特别留意播客中与此相关的内容 |

每项都可以填"跳过"——Agent 不强制填写。填完后 Agent 整理为结构化 YAML 格式存入 CLAUDE.md。

**存入 CLAUDE.md 的格式**：

```markdown
## User Persona
<!--
  由 audio-mind Agent 自动管理。
  要修改画像：直接编辑下方内容，或删除本段后重新对话。
-->

### 基本信息
- **name**: 张三
- **occupation**: 后端开发工程师（6年经验）
- **industry**: 互联网/SaaS
- **education**: 计算机科学本科

### 专业兴趣
- 大语言模型在垂直场景的落地
- AI Agent 与自动化工作流
- RAG（检索增强生成）实践
- 后端系统架构设计

### 非专业兴趣
- 认知科学与学习方法
- 效率工具与工作流优化
- 投资理财与个人财务管理
- 科技创业与产品思维

### 目标
- **短期**：将 AI Agent 集成到现有工作流，提升团队效率 30%+
- **长期**：构建个人知识管理体系，转型为 AI 产品经理或技术创业者

### 内容偏好
- **风格**：偏爱技术深度内容，喜欢具体案例和实践指导，排斥行业趋势泛泛科普
- **关注主题词**：AI Agent, RAG, 知识管理, 产品策略, 开源工具
- **倾向**：信任有数据和实验支撑的观点，对过度营销/炒作持怀疑态度

### 当前挑战
- 如何在团队中推动 AI 工具落地？
- 知识碎片化严重，如何系统性管理学到的内容？
- 是否应该从纯技术路线转向产品方向？
<!-- 完 -->
```

分析阶段，prompt 会完整注入该画像，要求 LLM 以画像为筛选依据，**只提取与该用户相关的内容**。

### 5.3 文件夹命名

格式：`{播客名}_{期号}_{简短主题词}`

| 数据 | 提取方式 | 示例 |
|------|---------|------|
| 播客名 | JSON-LD `partOfSeries.name` | 知行小酒馆 |
| 期号 | 标题正则 `E\d+` | E235 |
| 简短主题 | 标题去期号后截 ≤15 字 | AI改变你 |

### 5.4 输出文档

**`transcript.md`**：按时间轴排列的完整转写文本（含 `[HH:MM:SS]` 时间戳）。

**`insights.md`**：6 个结构化段落 —— 🎯核心观点 · 🔗与我的关联 · ✅行动项 · 💬关键引述 · ⚠️需批判看待 · 📚提到的资源。

### 5.5 文本分段

- 默认全文分析（1小时播客 ≈ 1.2万-2.2万 token）
- token > 80,000 触发分段（8000字/段 · 10%重叠）
- 各段摘要 → 一次 LLM 调用合并全局洞察

### 5.6 错误处理

三层架构：Pipeline try/except → 模块异常转换（DownloadError / TranscriptionError / AnalysisError）→ HTTP/API 层重试（tenacity + requests.Retry）

---

## 6. 实施计划（10 步）

| # | 内容 | 产出 |
|---|------|------|
| 1 | 项目脚手架 | pyproject.toml · .gitignore · 全目录 |
| 2 | 配置 + utils | .env · settings.yaml · api · config · logger |
| 3 | 异常 + 数据模型 | exceptions.py · models/*.py |
| 4 | Downloader | 小宇宙 og:audio + JSON-LD · RSS |
| 5 | Transcriber | faster-whisper + pydub |
| 6 | Prompt 模板 | analyze · summarize_chunk · synthesize |
| 7 | Analyzer | DeepSeek · Chunker · Synthesizer |
| 8 | 画像管理 + 文档生成 | 10 项引导问卷 · CLAUDE.md 读写 · transcript.md · insights.md |
| 9 | Pipeline 编排 | pipeline.py |
| 10 | 测试 + 端到端 | pytest + 真实播客跑通 |

---

## 7. 环境准备

| 东西 | 获取方式 |
|------|---------|
| **DeepSeek API Key** | [platform.deepseek.com/api_keys](https://platform.deepseek.com/api_keys) · 新用户送 500 万 token |
| **画像信息**（仅首次） | Agent 会列出 10 个引导问题，你逐项回答即可 |
| **播客链接** | 小宇宙 App → 分享 → 复制链接 → 粘贴到对话 |

`.env` 只需一行：
```bash
DEEPSEEK_API_KEY=sk-your-key-here
```

---

## 8. 验证方式

1. `uv run pytest` — 单元测试全覆盖
2. 对话中发真实链接 → 检查 `output/{播客名}_{期号}_{主题}/` 下 transcript.md + insights.md 正确生成
3. 确认画像采集流程（引导问题 → 用户填写 → 写入 CLAUDE.md → 后续自动读取）正常运作
