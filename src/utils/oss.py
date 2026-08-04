"""OSS 公共工具模块：阿里云 OSS 上传、签名、Bucket 管理

提取自 volcengine.py 和 alibaba.py 的重复 OSS 逻辑，
统一使用 oss2 SDK 进行文件上传，REST API 进行 Bucket 管理。
"""

import base64
import hashlib
import hmac
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from src.exceptions import WhisperRuntimeError, ConfigurationError
from src.utils.logger import setup_logger

logger = setup_logger("audio-mind.utils.oss")

# ── GMT 日期常量 ────────────────────────────────────────
_WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# ── 重试配置 ───────────────────────────────────────────
MAX_RETRIES = 3
RETRY_BACKOFF = 2.0


def gmt_now() -> str:
    """返回 GMT 格式时间字符串（locale-independent，强制英文缩写）"""
    now = datetime.now(timezone.utc)
    return (
        f"{_WEEKDAYS[now.weekday()]}, "
        f"{now.day:02d} {_MONTHS[now.month - 1]} {now.year} "
        f"{now.hour:02d}:{now.minute:02d}:{now.second:02d} GMT"
    )


def oss_sign(
    method: str,
    ak_secret: str,
    date: str,
    content_type: str = "",
    content_md5: str = "",
    resource: str = "/",
) -> str:
    """计算 OSS REST API HMAC-SHA1 签名

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


def oss_bucket_endpoint(bucket: str, region: str) -> str:
    """返回 bucket 级 OSS 域名"""
    return f"{bucket}.oss-{region}.aliyuncs.com"


def ensure_bucket(bucket: str, region: str, ak_id: str, ak_secret: str) -> None:
    """确保 OSS bucket 存在，不存在则创建

    使用 bucket 级域名（{bucket}.oss-{region}.aliyuncs.com），
    签名 resource 为 "/"。
    """
    bucket_endpoint = oss_bucket_endpoint(bucket, region)

    # ── 检查 bucket 是否存在 ──
    gmtnow = gmt_now()
    sig = oss_sign("HEAD", ak_secret, gmtnow, resource="/")

    resp = requests.head(
        f"https://{bucket_endpoint}/",
        headers={
            "Date": gmtnow,
            "Authorization": f"OSS {ak_id}:{sig}",
        },
        timeout=15,
    )

    if resp.status_code == 200:
        logger.info("OSS Bucket 已存在: %s", bucket)
        return

    # ── Bucket 不存在，创建 ──
    logger.info("创建 OSS Bucket: %s (%s)", bucket, region)
    gmtnow = gmt_now()

    create_body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<CreateBucketConfiguration>\n'
        f'  <LocationConstraint>{region}</LocationConstraint>\n'
        '</CreateBucketConfiguration>'
    )
    content_md5 = base64.b64encode(
        hashlib.md5(create_body.encode("utf-8")).digest()
    ).decode("utf-8")

    sig = oss_sign(
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
        logger.info("OSS Bucket 就绪: %s", bucket)
    else:
        raise WhisperRuntimeError(
            "创建 OSS Bucket 失败",
            detail=f"HTTP {resp.status_code}: {resp.text[:300]}\n"
                   f"请确认 AccessKey 拥有 OSS 写入权限 (AliyunOSSFullAccess)",
        )


def upload_to_oss(
    local_path: Path,
    ak_id: str,
    ak_secret: str,
    bucket: str,
    region: str,
) -> str:
    """上传文件到阿里云 OSS（使用 oss2 SDK），返回公网 URL

    Args:
        local_path: 本地文件路径
        ak_id: AccessKey ID
        ak_secret: AccessKey Secret
        bucket: OSS Bucket 名称
        region: OSS 区域

    Returns:
        文件公网 URL
    """
    try:
        import oss2
    except ImportError:
        raise ConfigurationError(
            "OSS 上传需要 oss2 库",
            detail="请运行: uv pip install oss2",
        )

    if not ak_id or not ak_secret:
        raise ConfigurationError(
            "OSS 上传需要阿里云凭证",
            detail="请在 .env 中设置 ALIBABA_ACCESS_KEY_ID 和 ALIBABA_ACCESS_KEY_SECRET",
        )

    endpoint = f"https://oss-{region}.aliyuncs.com"

    auth = oss2.Auth(ak_id, ak_secret)
    oss2_bucket = oss2.Bucket(auth, endpoint, bucket)

    stem = local_path.stem
    suffix = local_path.suffix or ".m4a"
    object_key = f"audio-mind/{stem}{suffix}"

    size_mb = local_path.stat().st_size / 1024 / 1024
    logger.info("上传音频到 OSS: %s/%s (%.1fMB)", bucket, object_key, size_mb)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            oss2_bucket.put_object_from_file(object_key, str(local_path))
            url = f"https://{bucket}.oss-{region}.aliyuncs.com/{object_key}"
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


def get_content_type(suffix: str) -> str:
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
