"""火山引擎 ASR 转写模块：豆包语音识别大模型 v3 标准版异步 API

使用火山引擎「大模型录音文件识别」标准版进行中文语音转写，
通过提交 (submit) + 轮询 (query) 异步模式处理完整音频，无需切片。

前置条件：
- 在火山引擎控制台开通「录音文件识别大模型」服务
- 获取 APP ID 和 Access Token，填入 .env
- 音频文件需有公网可访问的 URL（public_url）
- 如果 public_url 对火山引擎服务器不可达（45000006），
  自动将本地音频上传到阿里云 OSS 后重试
"""

import base64
import hashlib
import hmac
import json
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests

from src.exceptions import (
    AudioPreprocessError,
    WhisperRuntimeError,
    ConfigurationError,
)
from src.models import TranscriptResult, TranscriptSegment
from src.utils.config import get_settings, AppSettings
from src.utils.logger import setup_logger

logger = setup_logger("audio-mind.transcriber.volcengine")

# ── API 配置常量 ──────────────────────────────────────────
SUBMIT_API_URL = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/submit"
QUERY_API_URL = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/query"
DEFAULT_RESOURCE_ID = "volc.seedasr.auc"
DEFAULT_MODEL_NAME = "bigmodel"
DEFAULT_API_TIMEOUT = 30
POLL_INTERVAL = 5
MAX_POLL_SECONDS = 600
MAX_RETRIES = 3
RETRY_BACKOFF = 2.0


def _check_ffmpeg() -> None:
    """确认 ffprobe 可用"""
    try:
        subprocess.run(["ffprobe", "-version"], capture_output=True, timeout=10)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        raise AudioPreprocessError(
            "找不到 ffprobe，请确认 ffmpeg 已安装并加入 PATH\n"
            "安装: winget install ffmpeg  或  choco install ffmpeg"
        )


def _get_audio_duration(audio_path: Path) -> float:
    """用 ffprobe 获取音频时长（秒）"""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-show_entries", "format=duration",
        "-of", "csv=p=0",
        str(audio_path),
    ]
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=15,
        encoding="utf-8", errors="replace",
    )
    try:
        return float(result.stdout.strip())
    except ValueError:
        logger.warning("无法获取音频时长，假设为 30 分钟")
        return 30 * 60


def _detect_audio_format(audio_path: Path) -> str:
    """从文件扩展名推断音频格式"""
    suffix = audio_path.suffix.lower().lstrip(".")
    format_map = {
        "m4a": "m4a", "mp3": "mp3", "wav": "wav",
        "flac": "flac", "ogg": "ogg", "aac": "aac",
        "opus": "opus", "webm": "webm",
    }
    return format_map.get(suffix, suffix)


# ── OSS 上传辅助 ────────────────────────────────────────
_WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _gmt_now() -> str:
    """返回 GMT 格式时间字符串"""
    now = datetime.now(timezone.utc)
    return (
        f"{_WEEKDAYS[now.weekday()]}, "
        f"{now.day:02d} {_MONTHS[now.month - 1]} {now.year} "
        f"{now.hour:02d}:{now.minute:02d}:{now.second:02d} GMT"
    )


def _oss_sign(method: str, ak_secret: str, date: str,
              content_type: str = "", content_md5: str = "",
              resource: str = "/") -> str:
    """计算 OSS REST API HMAC-SHA1 签名"""
    string_to_sign = (
        f"{method.upper()}\n"
        f"{content_md5}\n"
        f"{content_type}\n"
        f"{date}\n"
        f"{resource}"
    )
    h = hmac.new(
        ak_secret.encode("utf-8"),
        string_to_sign.encode("utf-8"),
        hashlib.sha1,
    )
    return base64.b64encode(h.digest()).decode("utf-8")


def _oss_bucket_endpoint(bucket: str, region: str) -> str:
    """返回 bucket 级 OSS 域名"""
    return f"{bucket}.oss-{region}.aliyuncs.com"


def _ensure_bucket(bucket: str, region: str, ak_id: str, ak_secret: str) -> None:
    """确保 OSS bucket 存在，不存在则创建"""
    bucket_endpoint = _oss_bucket_endpoint(bucket, region)

    # 检查 bucket 是否存在
    gmtnow = _gmt_now()
    sig = _oss_sign("HEAD", ak_secret, gmtnow, resource="/")
    resp = requests.head(
        f"https://{bucket_endpoint}/",
        headers={"Date": gmtnow, "Authorization": f"OSS {ak_id}:{sig}"},
        timeout=15,
    )
    if resp.status_code == 200:
        logger.info("OSS Bucket 已存在: %s", bucket)
        return

    # 创建 bucket
    logger.info("创建 OSS Bucket: %s (%s)", bucket, region)
    gmtnow = _gmt_now()
    create_body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<CreateBucketConfiguration>\n'
        f'  <LocationConstraint>{region}</LocationConstraint>\n'
        '</CreateBucketConfiguration>'
    )
    content_md5 = base64.b64encode(
        hashlib.md5(create_body.encode("utf-8")).digest()
    ).decode("utf-8")
    sig = _oss_sign(
        "PUT", ak_secret, gmtnow,
        content_type="application/xml",
        content_md5=content_md5, resource="/",
    )
    resp = requests.put(
        f"https://{bucket_endpoint}/",
        headers={
            "Date": gmtnow,
            "Content-Type": "application/xml",
            "Content-MD5": content_md5,
            "Authorization": f"OSS {ak_id}:{sig}",
        },
        data=create_body,
        timeout=15,
    )
    if resp.status_code in (200, 201, 409):
        logger.info("OSS Bucket 就绪: %s", bucket)
    else:
        raise WhisperRuntimeError(
            "创建 OSS Bucket 失败",
            detail=f"HTTP {resp.status_code}: {resp.text[:300]}",
        )


def _get_mime_type(suffix: str) -> str:
    """根据文件后缀返回 MIME type"""
    mapping = {
        ".m4a": "audio/mp4", ".mp3": "audio/mpeg",
        ".wav": "audio/wav", ".flac": "audio/flac",
        ".ogg": "audio/ogg", ".aac": "audio/aac",
    }
    return mapping.get(suffix.lower(), "application/octet-stream")


def _upload_to_oss(local_path: Path, settings: AppSettings) -> str:
    """上传音频到阿里云 OSS（使用 oss2 SDK），返回公网 URL"""
    try:
        import oss2
    except ImportError:
        raise ConfigurationError(
            "OSS 上传需要 oss2 库",
            detail="请运行: uv pip install oss2",
        )

    aliyun = settings.alibaba
    if not aliyun.access_key_id or not aliyun.access_key_secret:
        raise ConfigurationError(
            "OSS 上传需要阿里云凭证",
            detail="请在 .env 中设置 ALIBABA_ACCESS_KEY_ID 和 ALIBABA_ACCESS_KEY_SECRET",
        )

    bucket_name = aliyun.oss_bucket
    region = aliyun.oss_region
    endpoint = f"https://oss-{region}.aliyuncs.com"

    auth = oss2.Auth(aliyun.access_key_id, aliyun.access_key_secret)
    bucket = oss2.Bucket(auth, endpoint, bucket_name)

    stem = local_path.stem
    suffix = local_path.suffix or ".m4a"
    object_key = f"audio-mind/{stem}{suffix}"

    size_mb = local_path.stat().st_size / 1024 / 1024
    logger.info("上传音频到 OSS: %s/%s (%.1fMB)", bucket_name, object_key, size_mb)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            bucket.put_object_from_file(object_key, str(local_path))
            url = f"https://{bucket_name}.oss-{region}.aliyuncs.com/{object_key}"
            logger.info("OSS 上传完成: %s", url)
            return url
        except oss2.exceptions.ServerError as e:
            logger.warning(
                "第 %d/%d 次 OSS 上传失败: %s - %s",
                attempt, MAX_RETRIES, e.code, str(e.message)[:200],
            )
        except Exception as e:
            logger.warning("第 %d/%d 次 OSS 上传错误: %s", attempt, MAX_RETRIES, e)

        if attempt < MAX_RETRIES:
            time.sleep(RETRY_BACKOFF * attempt)

    raise WhisperRuntimeError("OSS 上传失败", detail=f"重试 {MAX_RETRIES} 次后仍失败")


def _identify_speakers(
    segments: list,
    episode_info: str,
    settings: AppSettings,
) -> dict:
    """用 LLM 根据对话内容推断说话人身份，返回 speaker_id → 姓名 映射"""
    if len(segments) < 2:
        return {}

    # 收集各说话人的样本（每人前 800 字）
    speaker_samples = {}
    for seg in segments:
        # 提取 speaker ID（从 "说话人1: xxx" 格式中解析）
        text = seg.text
        if text.startswith("说话人") and ": " in text:
            sid = text.split(": ")[0].replace("说话人", "")
            content = text.split(": ", 1)[1] if ": " in text else ""
            if sid not in speaker_samples:
                speaker_samples[sid] = []
            if sum(len(s) for s in speaker_samples[sid]) < 800:
                speaker_samples[sid].append(content)

    if len(speaker_samples) < 2:
        return {}

    # 构建 prompt
    samples_text = ""
    for sid, texts in speaker_samples.items():
        samples_text += f"\n【说话人{sid}】:\n" + "\n".join(texts[:5]) + "\n"

    prompt = f"""以下是一期播客的对话片段，请根据内容推断每位"说话人"的身份。

播客信息：{episode_info}

提示：通常播客中，主讲嘉宾会大量分享技术经验和个人经历，主持人则负责开场、提问和串场。

各说话人发言样本：
{samples_text}

请返回 JSON，映射编号到姓名：
{{"1": "姓名", "2": "姓名"}}

只返回 JSON。"""

    try:
        import requests as req
        api_key = settings.deepseek.api_key
        resp = req.post(
            f"{settings.deepseek.base_url}/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": settings.deepseek.model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 200,
                "temperature": 0.1,
            },
            timeout=30,
        )
        content = resp.json()["choices"][0]["message"]["content"].strip()
        # 清理可能的 markdown 包裹
        if content.startswith("```"):
            content = content.split("\n", 1)[1].rsplit("\n", 1)[0]
        import json as _json
        mapping = _json.loads(content)
        logger.info("说话人识别结果: %s", mapping)
        return mapping
    except Exception as e:
        logger.warning("说话人识别失败: %s，保留原始标签", e)
        return {}


def transcribe_volcengine(
    audio_path: Path,
    settings: Optional[AppSettings] = None,
    public_url: Optional[str] = None,
    episode_info: str = "",
    progress_callback=None,
) -> TranscriptResult:
    """使用火山引擎豆包语音识别（标准版异步 API）进行转写

    流程：提交任务 → 轮询结果 → 解析文本 → 说话人识别。
    不需要音频切片，完整音频一次提交。

    Args:
        audio_path: 音频文件路径（仅用于获取时长和格式信息）
        settings: 应用配置
        public_url: 音频文件的公网可访问 URL（必需）
        episode_info: 播客信息（用于说话人识别）
        progress_callback: 进度回调 (percent: int, status: str)

    Returns:
        TranscriptResult（含全文和带说话人标签的片段）

    Raises:
        ConfigurationError: 未配置火山引擎凭证或缺少 public_url
        WhisperRuntimeError: API 调用失败
    """
    if settings is None:
        settings = get_settings()

    cfg = settings.volcengine

    if not cfg.app_id or not cfg.access_token:
        raise ConfigurationError(
            "火山引擎 ASR 凭证未配置",
            detail=(
                "请在 .env 中设置 VOLCENGINE_APP_ID 和 "
                "VOLCENGINE_ACCESS_TOKEN\n"
                "获取方式: https://console.volcengine.com/speech/app"
                " → 旧版控制台 → 创建应用"
            ),
        )

    if not public_url:
        raise ConfigurationError(
            "火山引擎 ASR 需要音频公网 URL",
            detail="请传入 public_url 参数（音频文件的公网可访问地址）",
        )

    _check_ffmpeg()

    try:
        duration = _get_audio_duration(audio_path)
    except Exception:
        duration = 0
        logger.warning("无法获取音频时长，将使用默认值")

    audio_format = _detect_audio_format(audio_path)
    logger.info("音频格式: %s, 时长: %.0fs", audio_format, duration)

    resource_id = cfg.resource_id or DEFAULT_RESOURCE_ID
    model_name = cfg.model_name or DEFAULT_MODEL_NAME

    if progress_callback:
        progress_callback(0, "正在提交转写任务...")

    # ── Step 1: 提交任务 ────────────────────────────────
    request_id = str(uuid.uuid4())

    submit_headers = {
        "X-Api-App-Key": cfg.app_id,
        "X-Api-Access-Key": cfg.access_token,
        "X-Api-Resource-Id": resource_id,
        "X-Api-Request-Id": request_id,
        "X-Api-Sequence": "-1",
        "Content-Type": "application/json",
    }

    submit_body = {
        "user": {"uid": cfg.app_id},
        "audio": {"url": public_url, "format": audio_format},
        "request": {
            "model_name": model_name,
            "enable_itn": True,
            "enable_punc": True,
            "enable_ddc": True,
            "enable_speaker_info": True,
        },
    }

    last_error = ""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.post(
                SUBMIT_API_URL,
                headers=submit_headers,
                json=submit_body,
                timeout=DEFAULT_API_TIMEOUT,
            )
        except requests.Timeout:
            last_error = "提交请求超时 (>%ds)" % DEFAULT_API_TIMEOUT
            logger.warning("第 %d/%d 次: %s", attempt, MAX_RETRIES, last_error)
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF * attempt)
            continue
        except requests.RequestException as e:
            last_error = str(e)
            logger.warning("第 %d/%d 次: 网络错误 - %s", attempt, MAX_RETRIES, last_error)
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF * attempt)
            continue

        status_code = resp.headers.get("X-Api-Status-Code", "")
        status_msg = resp.headers.get("X-Api-Message", "")

        if status_code == "20000000":
            logger.info("转写任务已成功提交")
            break
        else:
            last_error = "[%s] %s" % (status_code, status_msg)
            logger.warning("第 %d/%d 次: 提交失败 - %s", attempt, MAX_RETRIES, last_error)
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF * attempt)
            continue
    else:
        raise WhisperRuntimeError(
            "火山引擎 ASR 提交任务失败",
            detail="重试 %d 次后仍失败: %s" % (MAX_RETRIES, last_error),
        )

    if progress_callback:
        progress_callback(10, "任务已提交，等待转写结果...")

    # ── Step 2: 轮询结果 ────────────────────────────────
    query_headers = {
        "X-Api-App-Key": cfg.app_id,
        "X-Api-Access-Key": cfg.access_token,
        "X-Api-Resource-Id": resource_id,
        "X-Api-Request-Id": request_id,
        "Content-Type": "application/json",
    }

    text = ""
    segments = []
    poll_start = time.time()
    consecutive_bad_url = 0
    oss_retried = False
    url = public_url

    while True:
        elapsed = time.time() - poll_start
        if elapsed > MAX_POLL_SECONDS:
            raise WhisperRuntimeError(
                "火山引擎 ASR 转写超时",
                detail="等待 %ds 后仍未完成" % MAX_POLL_SECONDS,
            )

        poll_pct = min(10 + int((elapsed / MAX_POLL_SECONDS) * 80), 90)
        if progress_callback:
            progress_callback(poll_pct, "等待转写结果... (%ds)" % int(elapsed))

        try:
            resp = requests.post(
                QUERY_API_URL,
                headers=query_headers,
                json={},
                timeout=DEFAULT_API_TIMEOUT,
            )
        except requests.Timeout:
            logger.warning("查询请求超时，%ds 后重试...", POLL_INTERVAL)
            time.sleep(POLL_INTERVAL)
            continue
        except requests.RequestException as e:
            logger.warning("查询网络错误: %s，%ds 后重试...", e, POLL_INTERVAL)
            time.sleep(POLL_INTERVAL)
            continue

        status_code = resp.headers.get("X-Api-Status-Code", "")
        status_msg = resp.headers.get("X-Api-Message", "")

        if status_code == "20000000":
            try:
                result = resp.json()
                text = result.get("result", {}).get("text", "")
                utterances = result.get("result", {}).get("utterances", [])
                if utterances:
                    for u in utterances:
                        speaker = u.get("additions", {}).get("speaker", "")
                        label = f"说话人{speaker}: " if speaker else ""
                        segments.append(TranscriptSegment(
                            start=u.get("start_time", 0) / 1000.0,
                            end=u.get("end_time", 0) / 1000.0,
                            text=f"{label}{u.get('text', '')}",
                        ))
                    # Rebuild full_text from segments for consistency
                    text = "\n".join(s.text for s in segments)
                logger.info("转写完成: %d 字符, %d 片段", len(text), len(segments))
                break
            except json.JSONDecodeError:
                raise WhisperRuntimeError(
                    "火山引擎 ASR 响应解析失败",
                    detail="JSON 解析错误: %s" % resp.text[:200],
                )
        elif status_code in ("20000001", "20000002"):
            state = "处理中" if status_code == "20000001" else "排队中"
            logger.debug("转写%s，%ds 后重试...", state, POLL_INTERVAL)
            consecutive_bad_url = 0
            time.sleep(POLL_INTERVAL)
            continue
        elif status_code == "20000003":
            logger.info("音频为静音/无声段")
            text = ""
            break
        elif status_code == "45000006":
            consecutive_bad_url += 1
            if consecutive_bad_url >= 2 and not oss_retried:
                logger.warning(
                    "CDN URL 不可达，尝试上传到 OSS 后重试..."
                )
                try:
                    oss_url = _upload_to_oss(audio_path, settings)
                    # --- 用 OSS URL 重新提交 ---
                    new_request_id = str(uuid.uuid4())
                    submit_headers["X-Api-Request-Id"] = new_request_id
                    query_headers["X-Api-Request-Id"] = new_request_id
                    submit_body["audio"]["url"] = oss_url
                    request_id = new_request_id
                    url = oss_url

                    submit_resp = requests.post(
                        SUBMIT_API_URL,
                        headers=submit_headers,
                        json=submit_body,
                        timeout=DEFAULT_API_TIMEOUT,
                    )
                    sub_code = submit_resp.headers.get("X-Api-Status-Code", "")
                    if sub_code == "20000000":
                        logger.info("OSS URL 重新提交成功")
                        oss_retried = True
                        poll_start = time.time()
                        consecutive_bad_url = 0
                        continue
                    else:
                        logger.error(
                            "OSS URL 提交失败: [%s] %s",
                            sub_code, submit_resp.headers.get("X-Api-Message", ""),
                        )
                except Exception as e:
                    logger.error("OSS 上传/重提交失败: %s", e)
                # Fall through — wait and try again
            time.sleep(POLL_INTERVAL)
            continue
        else:
            logger.warning("查询返回异常状态: [%s] %s", status_code, status_msg)
            consecutive_bad_url = 0
            time.sleep(POLL_INTERVAL)
            continue

    if progress_callback:
        progress_callback(95, "转写完成，整理结果...")

    result = TranscriptResult(
        segments=segments,
        full_text=text,
        language="zh",
        duration=duration,
    )

    # ── 说话人识别：用 LLM 推断编号对应的真实姓名 ──
    if episode_info and segments:
        speaker_map = _identify_speakers(segments, episode_info, settings)
        if speaker_map:
            for seg in result.segments:
                if seg.text.startswith("说话人") and ": " in seg.text:
                    sid = seg.text.split(": ")[0].replace("说话人", "")
                    if sid in speaker_map:
                        seg.text = seg.text.replace(
                            f"说话人{sid}: ", f"{speaker_map[sid]}: ", 1
                        )
            # 重建 full_text
            result.full_text = "\n".join(s.text for s in result.segments)

    logger.info(
        "火山引擎转写完成: %d 字符, ~%d tokens",
        len(text), result.token_estimate(),
    )

    return result
