"""阿里云 ASR 转写模块：智能语音交互（NLS）录音文件识别

使用阿里云智能语音交互 REST API，通过 HMAC-SHA1 签名鉴权。
长音频自动分片（单段 ≤60 秒），直接 POST 二进制音频数据。

前置条件：
- 阿里云 RAM 用户，授权 AliyunNLSFullAccess
- AccessKey ID + Secret 填入 .env
"""

import base64
import hashlib
import hmac
import json
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
from src.models import TranscriptResult
from src.utils.config import get_settings, AppSettings
from src.utils.logger import setup_logger

logger = setup_logger("audio-mind.transcriber.alibaba")

# ── API 常量 ──────────────────────────────────────────
NLS_ENDPOINT = "https://nls-slp.cn-shanghai.aliyuncs.com/"
API_VERSION = "2019-09-27"
CHUNK_SECONDS = 55                     # 每段最多 55 秒（API 限制 60 秒）
MAX_RETRIES = 3
RETRY_BACKOFF = 2.0


# locale-independent English day/month names for GMT dates
_WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _gmt_now() -> str:
    """返回 GMT 格式时间字符串（locale-independent，强制英文缩写）"""
    now = datetime.now(timezone.utc)
    return (
        f"{_WEEKDAYS[now.weekday()]}, "
        f"{now.day:02d} {_MONTHS[now.month - 1]} {now.year} "
        f"{now.hour:02d}:{now.minute:02d}:{now.second:02d} GMT"
    )


def _sign_aliyun_rpc(method: str, params: dict, secret: str) -> str:
    """阿里云 RPC 风格 HMAC-SHA1 签名

    用于 nls-slp 等阿里云 OpenAPI 端点。
    签名算法: https://help.aliyun.com/document_detail/25490.html
    """
    # 1. 排序参数
    sorted_params = sorted(params.items())

    # 2. 构建 canonical query string
    canonical = "&".join(
        f"{_percent_encode(k)}={_percent_encode(str(v))}"
        for k, v in sorted_params
    )

    # 3. 构建 string to sign
    string_to_sign = (
        f"{method.upper()}&"
        f"{_percent_encode('/')}&"
        f"{_percent_encode(canonical)}"
    )

    # 4. HMAC-SHA1 签名
    key = (secret + "&").encode("utf-8")
    h = hmac.new(key, string_to_sign.encode("utf-8"), hashlib.sha1)
    return base64.b64encode(h.digest()).decode("utf-8")


def _percent_encode(s: str) -> str:
    """阿里云签名专用 URL 编码"""
    import urllib.parse
    return urllib.parse.quote(str(s), safe="~")


def _sign_nls_dataplus(method: str, body: str, secret: str) -> str:
    """NLS Dataplus 风格 HMAC-SHA1 签名

    用于 nlsapi.aliyun.com 端点。
    签名字符串: METHOD\nAccept\nContent-MD5\nContent-Type\nDate
    """
    body_md5 = base64.b64encode(
        hashlib.md5(body.encode("utf-8")).digest()
    ).decode("utf-8")
    gmtnow = _gmt_now()
    string_to_sign = (
        f"{method.upper()}\n"
        f"application/json\n"
        f"{body_md5}\n"
        f"application/json\n"
        f"{gmtnow}"
    )
    h = hmac.new(secret.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha1)
    signature = base64.b64encode(h.digest()).decode("utf-8")
    return signature, gmtnow


def _make_nls_request(body: dict, ak_id: str, ak_secret: str) -> dict:
    """向 NLS 录音文件识别 API 发送请求（Dataplus 鉴权）"""
    body_str = json.dumps(body)
    signature, gmtnow = _sign_nls_dataplus("POST", body_str, ak_secret)

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Date": gmtnow,
        "Authorization": f"Dataplus {ak_id}:{signature}",
    }

    resp = requests.post(
        "https://nlsapi.aliyun.com/transcriptions",
        headers=headers,
        data=body_str,
        timeout=30,
    )
    return _handle_nls_response(resp)


def _handle_nls_response(resp: requests.Response) -> dict:
    """解析 NLS API 响应"""
    if resp.status_code != 200:
        raise WhisperRuntimeError(
            "阿里云 NLS API 请求失败",
            detail=f"HTTP {resp.status_code}: {resp.text[:300]}",
        )
    try:
        result = resp.json()
    except json.JSONDecodeError:
        raise WhisperRuntimeError(
            "阿里云 NLS API 响应解析失败",
            detail=resp.text[:300],
        )

    if result.get("status") not in (20000000, None):
        raise WhisperRuntimeError(
            "阿里云 NLS API 返回错误",
            detail=json.dumps(result, ensure_ascii=False),
        )

    return result


def _submit_file_trans(oss_link: str, ak_id: str, ak_secret: str, app_key: str = "nls-service-multi-domain") -> str:
    """提交录音文件识别任务

    Args:
        oss_link: 音频文件公网 URL（OSS 或 CDN）
        ak_id: AccessKey ID
        ak_secret: AccessKey Secret
        app_key: 模型标识

    Returns:
        task_id: 任务 ID
    """
    body = {
        "app_key": app_key,
        "oss_link": oss_link,
        "enable_words": False,
        "enable_timestamp": False,
    }
    result = _make_nls_request(body, ak_id, ak_secret)
    task_id = result.get("id")
    if not task_id:
        raise WhisperRuntimeError(
            "提交识别任务失败：未获取到 task_id",
            detail=json.dumps(result, ensure_ascii=False),
        )
    logger.info(f"识别任务已提交: task_id={task_id}")
    return task_id


def _poll_transcription(task_id: str, ak_id: str, ak_secret: str, max_wait: int = 600) -> str:
    """轮询录音文件识别结果

    Args:
        task_id: 任务 ID
        ak_id: AccessKey ID
        ak_secret: AccessKey Secret
        max_wait: 最大等待秒数（默认 10 分钟）

    Returns:
        转写文本
    """
    signature, gmtnow = _sign_nls_dataplus("GET", "", ak_secret)
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Date": gmtnow,
        "Authorization": f"Dataplus {ak_id}:{signature}",
    }

    url = f"https://nlsapi.aliyun.com/transcriptions/{task_id}"
    interval = 3
    elapsed = 0

    while elapsed < max_wait:
        resp = requests.get(url, headers=headers, timeout=30)
        result = _handle_nls_response(resp)

        status = result.get("status", 0)
        if status == 20000000:
            # 识别完成
            text = result.get("result", "")
            if isinstance(text, list):
                # 多句结果拼接
                text = "".join(
                    sentence.get("text", "") for sentence in text
                )
            logger.info(f"识别完成: {len(text)} 字符")
            return text
        elif status == 20000003:
            # 静音/无语音
            logger.info("音频为静音段")
            return ""
        elif status in (20000001, 20000002, None):
            # 处理中
            logger.info(f"识别中... (已等待 {elapsed}s)")
            time.sleep(interval)
            elapsed += interval
            interval = min(interval * 1.5, 15)
        else:
            raise WhisperRuntimeError(
                f"识别失败: status={status}",
                detail=json.dumps(result, ensure_ascii=False),
            )

    raise WhisperRuntimeError(
        "识别超时",
        detail=f"等待 {max_wait}s 后仍未完成",
    )


def transcribe_alibaba(
    audio_path: Path,
    settings: Optional[AppSettings] = None,
    progress_callback=None,
    public_url: Optional[str] = None,
) -> TranscriptResult:
    """使用阿里云智能语音交互进行转写

    使用录音文件识别 API，需要音频公网可访问。
    策略：
    1. 优先使用传入的 public_url（如播客原始 CDN 链接，跳过 OSS 上传）
    2. 否则：将音频上传到 OSS，获取公网 URL 后提交识别任务

    Args:
        audio_path: 音频文件路径（OSS 上传时需要）
        settings: 应用配置
        progress_callback: 进度回调
        public_url: 音频公网 URL（如果已可公网访问，跳过 OSS 上传）

    Returns:
        TranscriptResult
    """
    if settings is None:
        settings = get_settings()

    cfg = settings.alibaba

    if not cfg.access_key_id or not cfg.access_key_secret:
        raise ConfigurationError(
            "阿里云 ASR 凭证未配置",
            detail=(
                "请在 .env 中设置 ALIBABA_ACCESS_KEY_ID 和 ALIBABA_ACCESS_KEY_SECRET\n"
                "获取方式: https://ram.console.aliyun.com/users → 创建 RAM 用户\n"
                "授权策略: AliyunNLSFullAccess"
            ),
        )

    ak_id = cfg.access_key_id
    ak_secret = cfg.access_key_secret
    app_key = cfg.app_key

    # ── 获取公网 URL ──
    if public_url:
        oss_url = public_url
        logger.info(f"使用播客原始 CDN 链接（跳过 OSS 上传）")
    else:
        if progress_callback:
            progress_callback(5, "准备上传音频...")
        oss_url = _upload_to_oss(audio_path, ak_id, ak_secret, settings)

    if progress_callback:
        progress_callback(15, "提交识别任务...")

    # ── 提交识别任务 ──
    task_id = _submit_file_trans(oss_url, ak_id, ak_secret, app_key)

    if progress_callback:
        progress_callback(20, "等待识别结果...")

    # ── 轮询直到完成 ──
    max_wait = cfg.max_wait
    full_text = _poll_transcription(task_id, ak_id, ak_secret, max_wait=max_wait)

    if progress_callback:
        progress_callback(95, "整理结果...")

    result = TranscriptResult(
        segments=[],
        full_text=full_text,
        language="zh",
        duration=0,
    )

    logger.info(
        f"阿里云转写完成: {len(full_text)} 字符, "
        f"~{result.token_estimate()} tokens"
    )

    return result


def _oss_sign(
    method: str,
    ak_secret: str,
    date: str,
    content_type: str = "",
    content_md5: str = "",
    resource: str = "/",
) -> str:
    """计算 OSS REST API 签名

    Args:
        method: HTTP 方法 (GET/PUT/HEAD)
        ak_secret: AccessKey Secret
        date: GMT 日期头
        content_type: Content-Type（PUT 时必填）
        content_md5: Content-MD5（有 body 时必填）
        resource: 规范化资源路径（如 /object_key，不含 bucket）
    """
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
    """确保 OSS bucket 存在，不存在则创建

    使用 bucket 级域名（{bucket}.oss-{region}.aliyuncs.com），
    签名 resource 为 "/"。
    """
    bucket_endpoint = _oss_bucket_endpoint(bucket, region)

    # ── 检查 bucket 是否存在 ──
    gmtnow = _gmt_now()
    sig = _oss_sign("HEAD", ak_secret, gmtnow, resource="/")

    resp = requests.head(
        f"https://{bucket_endpoint}/",
        headers={
            "Date": gmtnow,
            "Authorization": f"OSS {ak_id}:{sig}",
        },
        timeout=15,
    )

    if resp.status_code == 200:
        logger.info(f"OSS Bucket 已存在: {bucket}")
        return

    # ── Bucket 不存在，创建 ──
    logger.info(f"创建 OSS Bucket: {bucket} ({region})")
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
        content_md5=content_md5,
        resource="/",
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
        logger.info(f"OSS Bucket 就绪: {bucket}")
    else:
        raise WhisperRuntimeError(
            "创建 OSS Bucket 失败",
            detail=f"HTTP {resp.status_code}: {resp.text[:300]}\n"
                   f"请确认 AccessKey 拥有 OSS 写入权限 (AliyunOSSFullAccess)",
        )


def _upload_to_oss(
    local_path: Path,
    ak_id: str,
    ak_secret: str,
    settings: AppSettings,
) -> str:
    """上传音频文件到阿里云 OSS 并返回公网 URL"""
    bucket = settings.alibaba.oss_bucket
    region = settings.alibaba.oss_region
    bucket_endpoint = _oss_bucket_endpoint(bucket, region)

    _ensure_bucket(bucket, region, ak_id, ak_secret)

    stem = local_path.stem
    suffix = local_path.suffix or ".m4a"
    object_key = f"audio-mind/{stem}{suffix}"
    resource = f"/{object_key}"

    with open(local_path, "rb") as f:
        audio_data = f.read()

    content_type = _get_content_type(suffix)
    gmtnow = _gmt_now()
    sig = _oss_sign("PUT", ak_secret, gmtnow, content_type=content_type, resource=resource)

    headers = {
        "Date": gmtnow,
        "Content-Type": content_type,
        "Authorization": f"OSS {ak_id}:{sig}",
    }

    size_mb = len(audio_data) / 1024 / 1024
    logger.info(f"上传音频到 OSS: {bucket}/{object_key} ({size_mb:.1f}MB)")

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.put(
                f"https://{bucket_endpoint}/{object_key}",
                headers=headers,
                data=audio_data,
                timeout=300,
            )
            if resp.status_code == 200:
                url = f"https://{bucket_endpoint}/{object_key}"
                logger.info(f"OSS 上传完成: {url}")
                return url
            else:
                logger.warning(
                    f"第 {attempt}/{MAX_RETRIES} 次 OSS 上传失败: "
                    f"HTTP {resp.status_code} {resp.text[:200]}"
                )
        except requests.RequestException as e:
            logger.warning(f"第 {attempt}/{MAX_RETRIES} 次 OSS 上传网络错误: {e}")

        if attempt < MAX_RETRIES:
            time.sleep(RETRY_BACKOFF * attempt)

    raise WhisperRuntimeError(
        "OSS 上传失败",
        detail=f"重试 {MAX_RETRIES} 次后仍失败",
    )


def _get_content_type(suffix: str) -> str:
    """根据文件后缀返回 MIME type"""
    mapping = {
        ".m4a": "audio/mp4",
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".flac": "audio/flac",
        ".ogg": "audio/ogg",
        ".aac": "audio/aac",
        ".wma": "audio/x-ms-wma",
    }
    return mapping.get(suffix.lower(), "application/octet-stream")
