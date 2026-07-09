# audio-mind 项目讨论纪要

> 记录从项目启动到设计定稿的全过程讨论，便于后续回溯决策背景。

---

## 第 1 轮：需求理解与技术方案初稿

**时间**：2026-06-29

**讨论要点**：

- 用户展示了 [CLAUDE.md](CLAUDE.md) 作为项目规格文件，要求完成 Agent 设计
- 用户自述背景：Agent 开发小白，只会写基础代码，需要引导
- 产出初版设计方案：
  - 技术栈：`uv` + `faster-whisper`（本地）+ `DeepSeek`（LLM）+ `pytest`
  - CLI 入口：`python -m src.main --url <播客链接>`
  - 画像存储：`config/persona.yaml`
  - 输出：终端打印 + JSON 文件

**关键决策**：

| 决策 | 结论 |
|------|------|
| 包管理 | `uv`（速度快，pyproject.toml 统一管理） |
| 语音转写 | `faster-whisper`（免费离线，中文 large-v3） |
| LLM | DeepSeek API（¥1/百万 token，128K 上下文，OpenAI 兼容） |
| 存储 | 文件系统，不用数据库 |

---

## 第 2 轮：技术方案验证——小宇宙音频到底怎么抓？

**用户质疑**：

> 小宇宙的分享链接只是一个引导下载 App 的页面，你怎么从中提取音频？

**实际验证**：

- 目标链接：`https://www.xiaoyuzhoufm.com/episode/6a06c4b91b7bd50295331e94`（知行小酒馆 E235，82 分钟）
- 用 `curl` 直接抓取 HTML，发现：
  - 页面是 **Next.js 服务端渲染（SSR）**，不需要执行 JavaScript
  - `<meta property="og:audio">` 直接包含 CDN 音频链接
  - CDN 地址 `media.xyzcdn.net` 是阿里云 OSS，无需 token/鉴权，HTTP 200，76MB
  - `<script name="schema:podcast-show">`（JSON-LD）包含完整元数据：播客名、时长、节目笔记（含时间轴 + 术语解释）
- **结论**：两行代码搞定，方案完全可行

**方案修正**：小宇宙直接抓取从"实验性尝试"升级为"主路径"，RSS 作为备选。

---

## 第 3 轮：输出结构调整

**用户需求 1**：产出两份 `.md` 文档（转写文本 + 洞察报告），存入以播客主题命名的中文文件夹。

**方案变更**：
- `output/{播客主题}/transcript.md` — 完整转写
- `output/{播客主题}/insights.md` — 个性化洞察

**用户需求 2**：画像不要每次手动输入，一次采集、长期存储。

**方案变更**：画像持久化到 `CLAUDE.md` 的 `## User Persona` 段，首次采集后后续自动读取。把 `config/persona.yaml` 去掉。

---

## 第 4 轮：交互方式与命名优化

**用户需求 1**：不需要 CLI，在 VSCode Claude Code 对话中粘贴链接即可。

**方案变更**：去掉 `python -m src.main --url` CLI；用户直接在对话中发链接，Agent 自动识别并执行。

**用户需求 2**：文件夹命名太长，需要包含播客名和期号。

**方案变更**：
- 命名格式：`{播客名}_{期号}_{简短主题}`（示例：`知行小酒馆_E235_AI改变你`）
- 播客名来自 JSON-LD `partOfSeries.name`
- 期号来自标题正则提取
- 简短主题截取标题关键词 ≤15 字

---

## 第 5 轮：画像采集细节

**用户反馈**：

> 你要让用户一次采集、长期使用，那画像必须足够详细。用户不知道你需要什么信息，你直接列出需要提供的画像信息给用户。

**方案变更**：

- 首次使用时不要求用户自述，而是逐项列出 **10 项引导问题**
- 问题覆盖：基本信息（4 项）、兴趣（2 项）、目标（2 项）、偏好（1 项）、挑战（1 项）
- 每项可填"跳过"，不强制
- 填完后 Agent 整理为结构化 YAML 写入 CLAUDE.md
- 后续运行直接从 CLAUDE.md 读取

**画像存储格式示例**：

```markdown
## User Persona
### 基本信息
- name / occupation / industry / education
### 专业兴趣
- ...
### 非专业兴趣
- ...
### 目标
- 短期 / 长期
### 内容偏好
- 风格 / 关注主题词 / 倾向
### 当前挑战
- ...
```

---

## 第 6 轮：CLAUDE.md 修改

**根据调研结果和用户反馈，修改了 CLAUDE.md 中 5 处**：

| # | 位置 | 修改内容 |
|---|------|---------|
| 1 | §1 | "数据库" → "存储"（本项目不使用数据库） |
| 2 | §2 | CLI 调用方式 → Claude Code 对话驱动 |
| 3 | §4 | `config/persona.yaml` → CLAUDE.md `## User Persona` 段持久化 |
| 4 | §6 | 小宇宙 Gotcha 追加实测验证结论（SSR + og:audio + 阿里云 OSS 无需鉴权） |
| 5 | §6 | `config/persona.yaml` 引用 → CLAUDE.md 引用 |

---

## 最终设计定稿

| 维度 | 结论 |
|------|------|
| **运行方式** | Claude Code 对话驱动，用户粘贴链接即可 |
| **音频下载** | requests + BeautifulSoup4 解析小宇宙 og:audio + JSON-LD（已实测验证） |
| **语音转写** | faster-whisper large-v3 本地转写，VAD 过滤静音 |
| **LLM 分析** | DeepSeek API，128K 上下文，¥1/百万 token |
| **画像存储** | CLAUDE.md `## User Persona` 段，首次使用时 10 项引导问题采集 |
| **输出文档** | `output/{播客名}_{期号}_{主题}/transcript.md` + `insights.md` |
| **包管理** | uv + pyproject.toml |
| **测试** | pytest |
| **存储** | 文件系统（Markdown），无数据库 |

**产出物**：
- [CLAUDE.md](CLAUDE.md) — 项目规格 + 用户画像（持久化）
- [DESIGN.md](DESIGN.md) — 产品与技术设计文档
- 待实施：10 步实施计划（见 DESIGN.md 第 6 节）
