---
name: "audio-mind-pipeline"
description: >
  运行和调试 audio-mind 播客洞察 Agent 的 Pipeline（小宇宙下载→语音转写→DeepSeek分析）。
  当用户提供小宇宙播客链接并请求运行/分析、Pipeline 报错涉及转录或 ASR、
  火山引擎 45000000/45000006/45000010 错误、OSS 上传失败、说话人分离问题、
  转录文件为空时使用。
  不用于：非 audio-mind 项目的 Python 调试、其他 ASR 服务独立配置。
version: "2.0.0"
author: "Hermes Agent"
tags: ["audio-mind", "volcengine", "ASR", "transcription", "pipeline", "deepseek", "xiaoyuzhou", "podcast", "debug", "oss", "speaker-diarization"]
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
- 火山引擎 ASR 返回 `45000000` / `45000006` / `45000010`
- OSS 上传失败（`NoSuchBucket` / `SignatureDoesNotMatch` / `AccessDenied`）
- 转录结果为空（`transcript.md` 只有标题无正文）
- 用户请求切换转写引擎、说话人分离、排查 OSS 凭证

## L1 症状速查表

| 症状 | 根因 | 进入 |
|------|------|------|
| `ModuleNotFoundError: pydantic_core` | Hermes venv 污染 | → Step A |
| `416 Requested Range Not Satisfiable` | 下载残留 | → Step B |
| `45000000 resourceId not allowed` | 端点与资源不匹配 | → Step C |
| `45000010 grant not found` | 授权记录缺失 | → Step D |
| `45000006 Invalid audio URI` | CDN URL 不可达 | → Step F |
| OSS 上传 `NoSuchBucket` | Bucket 不存在 | → Step G |
| OSS 上传 `SignatureDoesNotMatch` | 签名算法不兼容 | → Step H |
| OSS 上传 `AccessDenied` / `UserDisable` | AK 权限/状态问题 | → Step I |
| transcript.md 为空 | segments 空未回退 full_text | → Step J |
| 转写超时（>600s 无返回）| 引擎处理慢 | → Step E |
| 无说话人标签（一个 blob）| 未开 enable_speaker_info | → Step K |
| 说话人标为 "1"/"2" 非真名 | LLM 识别未触发或失败 | → Step L |

---

## Workflow / Steps

### Step 1: 确定运行环境

1. 确认工作目录：`cd D:/vibecoding/project/Agents/audio-mind`
2. 确认引擎：读取 `config/settings.yaml` → `transcriber.provider`
3. **必须**在命令前加 `PYTHONPATH=""`，否则 Hermes venv 会污染项目依赖
4. 确认 `oss2` 包已安装：`.venv/Scripts/python.exe -c "import oss2"`，若无则 `uv pip install oss2`

### Step 2: 清理残留并启动

```bash
rm -f temp_audio/* && PYTHONPATH="" .venv/Scripts/python.exe -m src.pipeline --url "<podcast_url>"
```

---

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
   - `SUBMIT_API_URL` = 标准版（异步 submit+query）→ 需用 `volc.seedasr.auc`
   - `FLASH_API_URL` = 极速版（同步）→ 需用 `volc.bigasr.auc.flash`
2. 控制台开通的版本 = 代码端点
3. 若端点错误 → 重写 `volcengine.py` 为标准版 submit+query 模式
4. 若端点正确 → 检查 `config/settings.yaml` 的 `volcengine.resource_id`
**验证**：提交任务后返回 `20000000`。

### Step D: 授权记录缺失 (45000010)

> 认证通过，端点正确，但 APP ID 无此 resource 的授权。

**操作（按顺序）**：
1. 等待 2~5 分钟（SaaS 存储同步延迟）
2. 确认控制台开通的是正确版本（极速版 ≠ 标准版，需分别开通）
3. 确认 APP ID 出现在服务详情页的「服务接口认证信息」中
4. 确认 header 名为 `X-Api-App-Key`（不是 `X-Api-App-Id`）
**验证**：提交任务后返回 `20000000`。
**Fallback**：若以上全部失败 → 切换到 `alibaba` 引擎。

### Step E: 转写超时 — Fallback

引擎切换优先级：`volcengine` → `alibaba` → `whisper`。

**操作**：
1. 修改 `config/settings.yaml` → `transcriber.provider`
2. 若切到 `whisper`：同步修改 `pipeline.timeout` 为 21600（6 小时）
3. 重跑 Pipeline
**验证**：转写阶段在 timeout 内完成。

---

### Step F: CDN URL 不可达 (45000006) — 自动 OSS Fallback

> 火山引擎提交成功，但轮询返回 45000006「Invalid audio URI」。
> 根因：喜马拉雅 CDN 链接是临时签名 URL，火山引擎服务器无法下载。

**自动处理**：`volcengine.py` 已内置 OSS 自动上传：
1. 检测连续 2 次 `45000006` → 自动调用 `_upload_to_oss(audio_path, settings)`
2. oss2 SDK 上传到 `audio-mind-temp` bucket（`cn-beijing`）
3. 获取 OSS 公网 URL → 生成新 request_id → 重新 submit → 重置 poll_start
4. 使用 `oss_retried` 标志防止无限循环

**前置条件**：
- OSS Bucket 存在且为公共读（见 Step G）
- AK 已启用且有 OSS 写入权限（见 Step I）
- `oss2` 包已安装

**验证**：日志中出现 `OSS 上传完成` + `OSS URL 重新提交成功`。

### Step G: OSS Bucket 不存在 (NoSuchBucket)

> OSS 上传返回 HTTP 404 `NoSuchBucket`。

**操作**：用户手动在阿里云控制台创建 Bucket：
1. 打开 [OSS 控制台](https://oss.console.aliyun.com/bucket)
2. 创建 Bucket：
   - 名称：`audio-mind-temp`
   - 区域：`cn-beijing`（与 `config/settings.yaml` 一致）
   - 存储类型：**标准存储**
   - 冗余：**本地冗余（LRS）**
   - ACL：**公共读**
   - 加密/日志/备份/HDFS：**全部不开**
3. 若用户选了其他区域 → 同步修改 `config/settings.yaml` 的 `alibaba.oss_region`

**验证**：`curl -sI "https://audio-mind-temp.oss-cn-beijing.aliyuncs.com/"` 返回 200。

### Step H: OSS 签名不匹配 (SignatureDoesNotMatch)

> REST API PUT 返回 403 `SignatureDoesNotMatch`。
> 根因：HMAC-SHA1 Signature V1 在某些 RAM 用户上不兼容。

**当前方案**：已改用 oss2 SDK（`bucket.put_object_from_file()`），oss2 自动处理签名版本协商。
**验证**：确认 `_upload_to_oss()` 使用 `oss2.Bucket` 而非 `requests.put`。
**Fallback**：若 oss2 也不可用 → 切换到 `alibaba` 引擎（自带 OSS 上传）。

### Step I: AK 权限/状态问题

> OSS 操作返回 `UserDisable` 或 `AccessDenied`。

**`UserDisable`** — AK 被禁用：
1. [RAM 控制台 → 用户](https://ram.console.aliyun.com/users)
2. 点击用户名 → 找 **AccessKey** 列表（在用户详情主页，**不是**「认证管理」标签页）
3. 确认 AK 状态为**「启用」**
4. ⚠️ 启用 RAM 用户登录 ≠ 启用 AccessKey，是两个独立开关

**`AccessDenied`** — 缺少权限：
1. 确认 RAM 用户已绑定 `AliyunOSSFullAccess` 策略
2. 若需设置对象 ACL → 还需 `oss:PutObjectAcl`（当前方案不依赖此权限）

**验证**：`oss2.Service(auth, endpoint).list_buckets()` 成功返回。

---

### Step J: 转录文件为空

> `transcript.md` 只有标题和元数据，无正文。
> 根因：`TranscriptGenerator.generate()` 只遍历 `segments`（whisper 有时间戳），火山引擎的 `full_text` 字段被忽略。

**自动处理**：`markdown_gen.py` 已修复，segments 为空时回退使用 full_text。

**验证**：`transcript.md` 文件大小应 > 50KB（正常 69 分钟播客约 80-90KB）。

### Step K: 无说话人标签

> 转录结果是纯文本，没有区分说话人。
> 根因：火山引擎 submit body 未加 `enable_speaker_info: true`。

**自动处理**：已添加到 submit body（`volcengine.py` 第 328 行）。
返回的 `utterances` 数组每个元素带 `additions.speaker` + `start_time` + `end_time` + `text`。

**限制**：2 人对话准确率高；3+ 人可能串人；声线相近可能被合并；Speaker ID 是匿名编号。

### Step L: 说话人编号未转真实姓名

> 转录显示「说话人1:」「说话人2:」而非真实姓名。
> 根因：LLM 说话人识别失败或 episode_info 未传入 pipeline。

**自动流程**：
1. `_identify_speakers()`: 每人取前 800 字样本
2. DeepSeek 推断身份，返回 `{"1": "姓名", "2": "姓名"}`
3. 自动替换 `TranscriptSegment.text` 中的标签
4. 重建 `full_text`

**常见问题**：
- 结果为「主持人」非真名 → episode_info 未包含主播名
- 名字对调 → 样本太少导致误判；手动修正：
  ```bash
  sed -i 's/说话人1:/徐文浩:/g; s/主持人:/任鑫:/g' transcript.md
  ```

**验证**：日志中出现 `说话人识别结果: {...}`。

---

## Tools Binding

| 工具 | 用途 |
|------|------|
| `terminal` | 执行 Pipeline、清理文件、安装 oss2、sed 替换、Git 操作 |
| `read_file` | 读取 `volcengine.py`、`settings.yaml`、`markdown_gen.py` |
| `patch` | 修改 `settings.yaml` 参数、修复 markdown_gen |
| `web_search` | 查找火山引擎/OSS API 文档 |
| `process` | 后台监控 Pipeline 进度（poll/wait/log） |

## Output Format

Pipeline 成功时，输出结构化报告：

```
## Pipeline 完成

| 播客 | <name> - <title> |
| 音频 | <size> MB / <duration> 分钟 |

### 耗时
| 阶段 | 耗时 |
|------|------|
| 下载 | <time> |
| OSS 上传 | <time> |
| 转写 | <time>（volcengine，<segments> 片段，说话人分离） |
| 分析 | <time>（DeepSeek） |
| **总计** | **<total>** |

### Token
| ASR 字数 | <chars> |
| LLM Input | <tokens> |
| LLM Output | <tokens> |

### 输出
- transcript.md: <path>（带时间戳+姓名）
- insights.md: <path>
```

## Constraints & Safety

- **不得**修改 `.env` 中的 API Key
- **不得**在未确认服务状态时反复调用 API（避免无效计费）
- 切换引擎前**必须**确认新引擎凭证已配置
- 本地 Whisper 跑长音频（>30min）前**必须**告知用户预估耗时
- OSS 上传前**必须**确认 Bucket 存在且公共读
- 说话人识别结果**必须**让用户确认
- Pipeline 跑完**必须**验证 transcript.md 有正文（>10KB）