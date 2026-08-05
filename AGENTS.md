# AGENTS.md

## 1. Project Overview
- 自动播客洞察 Agent：从播客平台（小宇宙 App 等）抓取音频，转写为文字，再根据用户性格画像提取有价值的洞察与行动项。
- 语言：Python（版本不限，自行选择合适的版本）
- 其余技术栈（音频下载、转写 API、LLM、存储、包管理等）由你自主调研后决定，尽量使用中国产品的API，选型请在 README 中说明理由。

## 2. Commands
- 安装依赖：根据你选择的包管理工具自行定义（uv 均可）
- 启动 Agent：在 Codex 对话中粘贴播客链接即可触发，Agent 自动识别并执行完整流程（内部通过 `python -m src.pipeline` 调用）
- 跑测试：你选的测试框架自行定义命令，跑通后再交付
- 你需要自己先跑通完整流程（下载 → 转写 → 分析），确认无报错后再提交给我验收。

## 3. Architecture
- 整体分为三阶段：抓取下载 → 音频转写 → 内容分析，目录结构由你设计。
- 在 README 中写清架构说明与数据流向，保持简洁，不要超过三段话。

## 4. Conventions
- Python 文件用 snake_case
- 所有 LLM Prompt 模板放 `prompts/` 目录，不在代码中硬编码长字符串
- 所有外部 API 调用必须有超时设置 + 重试机制
- 用户画像持久化存储在 AGENTS.md 的 `## User Persona` 段，首次使用时代理会逐项引导用户填写详细画像（10 项引导问题），之后每次运行自动读取。如需修改画像，直接编辑该段或删除后重新对话即可。
- 错误处理用自定义异常类，不要裸抛 `Exception`
- 所有开发、测试及代码操作过程必须输出详细日志并归档保存，便于问题追溯与复盘

## 5. Hard Constraints
- 必须用 Python，其余技术栈你自主决定，但要在 README 里给出选型理由
- 不要把音频文件提交到 Git（.gitignore 必须覆盖音频格式与临时文件）
- 不要在代码中硬编码任何 API Key，统一走 `.env`，`.env` 不进 Git
- 用户性格画像是分析的核心输入，提取内容必须与画像强相关，不要做泛泛的摘要
- 交付前你必须自己跑通一遍完整流程，输出示例结果供我查看，不要给我半成品

## 6. Gotchas
- 小宇宙 App 没有公开 API，音频链接通常可以从分享链接中提取，部分播客同时发布到 Apple Podcasts / RSS，可考虑走 RSS feed 作为备选抓取路径。（2026-06-29 已验证：小宇宙分享页面为 SSR 渲染，HTML 源码中 `<meta property=\"og:audio\">` 直接包含 CDN 音频链接——阿里云 OSS，无需鉴权；`<script name=\"schema:podcast-show\">` JSON-LD 含完整播客元数据。RSS feed 作为备选。）
- 中文播客转写注意 Whisper 对中文长音频的准确率和超时问题，自行评估是否需要切片
- 分析阶段如果转录文本很长，注意 LLM 的上下文窗口限制，提前设计分段策略
- 用户画像存储在本地 `persona.local.md` 中（不入 Git），第一次运行时 Agent 会引导你填写详细画像（10 项问题），之后自动读取。如需修改，直接编辑 `persona.local.md` 或删除该文件后重新对话

## 7. Skills

本项目配有 Codex / Hermes 专用 Skill，用于 Pipeline 运行与故障排查：
- **audio-mind-pipeline** — 详见 `.claude/skills/audio-mind-pipeline/SKILL.md`（v2.0.0）
  涵盖：引擎切换、火山引擎 45000000/45000006/45000010 错误诊断、OSS 自动上传桥接、
  说话人分离(speaker diarization)、LLM 说话人识别、转录为空修复、venv 污染修复、下载残留清理。

## User Persona
<!--
  用户画像已移至本地文件 persona.local.md（已被 .gitignore 排除，不会提交到仓库）。
  如需修改画像，直接编辑 persona.local.md，或删除该文件后重新引导填写。
-->
