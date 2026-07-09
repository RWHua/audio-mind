---
name: "audio-mind-pipeline"
description: >
  运行和调试 audio-mind 播客洞察 Agent 的 Pipeline（小宇宙下载→语音转写→DeepSeek分析）。
  当用户提供小宇宙播客链接并请求运行/分析、Pipeline 报错涉及转录或 ASR、
  或遇到火山引擎 45000000/45000010 错误时使用。
  不用于：非 audio-mind 项目的 Python 调试、其他 ASR 服务独立配置。
version: "1.0.0"
author: "Hermes Agent"
tags: ["audio-mind", "volcengine", "ASR", "transcription", "pipeline", "deepseek", "xiaoyuzhou", "podcast", "debug"]
arguments_schema:
  type: "object"
  properties:
    podcast_url:
      type: "string"
      description: "小宇宙播客单集链接"
    provider:
      type: "string"
      enum: ["whisper", "volcengine", "alibaba"]
      description: "转写引擎，默认从 config/settings.yaml 读取"
  required: ["podcast_url"]
---

# audio-mind Pipeline

## Role & Objective

你是 audio-mind 项目的运维 Agent。目标：让 Pipeline 从播客链接到洞察报告**一次跑通**。
项目路径：`D:\vibecoding\project\Agents\audio-mind`。

## Trigger Conditions

以下任一情况激活本 Skill：
- 用户提供小宇宙播客链接并请求分析/运行
- Pipeline 报错，涉及下载、转写、分析任一阶段
- 火山引擎 ASR 返回 `45000000` 或 `45000010`
- 用户请求切换转写引擎或排查 ASR 凭证

## Workflow / Steps

### Step 1: 确定运行环境

1. 确认工作目录：`cd D:/vibecoding/project/Agents/audio-mind`
2. 确认引擎：读取 `config/settings.yaml` → `transcriber.provider`
3. **必须**在命令前加 `PYTHONPATH=""`，否则 Hermes venv 会污染项目依赖

### Step 2: 清理残留并启动

```bash
rm -f temp_audio/* && PYTHONPATH="" .venv/Scripts/python.exe -m src.pipeline --url "<podcast_url>"
```

### Step 3: 错误分流

按症状匹配，进入对应子流程：

| 症状 | 进入 |
|------|------|
| `ModuleNotFoundError: pydantic_core` | → Step A |
| `416 Requested Range Not Satisfiable`（下载阶段） | → Step B |
| `45000000 resourceId X is not allowed`（转写阶段） | → Step C |
| `45000010 grant not found`（转写阶段） | → Step D |
| 转写超时（>600s 无返回）| → Step E |

### Step A: venv 污染

**操作**：确保命令前有 `PYTHONPATH=""`。
**验证**：重跑后不再报 pydantic_core 错误。

### Step B: 下载残留

**操作**：`rm -f temp_audio/*` 强制删除残留文件。
**原因**：上次下载完成但未清理，续传 Range 请求被 CDN 拒绝。
**验证**：重跑后下载阶段正常完成（显示 `下载完成: XX MB`）。

### Step C: 端点与 resource_id 不匹配 (45000000)

> API 端点不认识这个 resource_id。根因：代码调的 API 版本 ≠ 控制台开通的服务版本。

**操作**：
1. 读 `src/transcriber/volcengine.py` 顶部常量，确认当前端点：
   - `SUBMIT_API_URL` = 标准版（异步 submit+query）→ 需用 `volc.seedasr.auc` 或 `volc.bigasr.auc`
   - `FLASH_API_URL` = 极速版（同步 /recognize/flash）→ 需用 `volc.bigasr.auc.flash`
2. **规则**：控制台开通的版本 = 代码端点。火山引擎有 Flash/标准版/闲时版三套独立 API。
3. 若端点错误 → 重写 `volcengine.py` 为标准版 submit+query 模式
4. 若端点正确 → 检查 `config/settings.yaml` 的 `volcengine.resource_id` 是否配套
**验证**：提交任务后返回 `20000000`。

### Step D: 授权记录缺失 (45000010)

> 认证通过，端点正确，但 APP ID 无此 resource 的授权。

**操作（按顺序）**：
1. 等待 2~5 分钟（SaaS 存储同步延迟）
2. 确认控制台开通的是正确版本（极速版 ≠ 标准版，需分别开通）
3. 对比极速版和标准版的 Access Token（点击「显示」，可能不同）
4. 确认 APP ID 出现在服务详情页的「服务接口认证信息」中
5. 确认 header 名为 `X-Api-App-Key`（不是 `X-Api-App-Id`）
**验证**：提交任务后返回 `20000000`。
**Fallback**：若以上全部失败 → 切换到 `alibaba` 引擎（Step E）。

### Step E: 转写超时或引擎不可用 — Fallback

引擎切换优先级：`volcengine` → `alibaba` → `whisper`。

**操作**：
1. 修改 `config/settings.yaml` → `transcriber.provider`
2. 若切到 `whisper`：同步修改 `pipeline.timeout` 为 21600（6 小时，CPU 预估 4~6h）
3. 重跑 Pipeline
**验证**：转写阶段在 timeout 内完成。

## Tools Binding

| 工具 | 用途 |
|------|------|
| `terminal` | 执行 Pipeline、清理文件、API 连通性测试 |
| `read_file` | 读取 `volcengine.py` 端点常量、`settings.yaml` 配置 |
| `patch` | 修改 `settings.yaml` 的 provider/resource_id/timeout |
| `write_file` | 重写 `volcengine.py`（切换到标准版 API 时） |
| `web_search` | 查找火山引擎 API 文档（必要时） |

## Output Format

Pipeline 成功时，汇总以下信息：

```
## Pipeline 完成

| 播客 | <podcast_name> - <episode_title> |
| 音频 | <size> MB / <duration> 分钟 |

### 耗时
| 阶段 | 耗时 |
|------|------|
| 下载 | <time> |
| 转写 | <time>（<engine>） |
| 分析 | <time> |
| **总计** | **<total_time>** |

### Token 消耗
| DeepSeek Input | <tokens> |
| DeepSeek Output | <tokens> |
| **合计** | **<total_tokens>** |

### 输出
- transcript.md: <path>
- insights.md: <path>
```

## Constraints & Safety

- **不得**修改 `.env` 文件中的 API Key/Token（凭据不可泄露）
- **不得**在未确认控制台服务状态的情况下反复调用 API（避免无效计费）
- **不得**对未提供的播客链接做假设
- 切换引擎前**必须**确认新引擎的凭证已在 `.env` 中配置
- 本地 Whisper 跑长音频（>30min）前**必须**先告知用户预估耗时并确认
