"""Fix alibaba.py: remove OSS functions, import from src.utils.oss, adapt _sign_nls_dataplus"""
import re

with open('src/transcriber/alibaba.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Add imports from src.utils.oss
old_import = """from src.exceptions import (
    AudioPreprocessError,
    WhisperRuntimeError,
    ConfigurationError,
)
from src.models import TranscriptResult
from src.utils.config import get_settings, AppSettings
from src.utils.logger import setup_logger"""

new_import = """from src.exceptions import (
    AudioPreprocessError,
    WhisperRuntimeError,
    ConfigurationError,
)
from src.models import TranscriptResult
from src.utils.config import get_settings, AppSettings
from src.utils.logger import setup_logger
from src.utils.oss import (
    gmt_now,
    oss_sign,
    oss_bucket_endpoint,
    ensure_bucket,
    upload_to_oss,
    get_content_type,
)"""

assert old_import in content, "Import block not found"
content = content.replace(old_import, new_import)
print("1. Imports added")

# 2. Remove _WEEKDAYS and _MONTHS constants
old_weekdays = """# locale-independent English day/month names for GMT dates
_WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]"""

new_weekdays = """# locale-independent English day/month names for GMT dates (delegated to src.utils.oss)"""

assert old_weekdays in content, "Weekdays constants not found"
content = content.replace(old_weekdays, new_weekdays)
print("2. Weekday constants removed")

# 3. Remove _gmt_now function
old_gmt = """

def _gmt_now() -> str:
    \"\"\"返回 GMT 格式时间字符串（locale-independent，强制英文缩写）\"\"\"
    now = datetime.now(timezone.utc)
    return (
        f\"{_WEEKDAYS[now.weekday()]}, "
        f\"{now.day:02d} {_MONTHS[now.month - 1]} {now.year} "
        f\"{now.hour:02d}:{now.minute:02d}:{now.second:02d} GMT\"
    )"""

assert old_gmt in content, "_gmt_now not found"
content = content.replace(old_gmt, "")
print("3. _gmt_now removed")

# 4. Update _sign_nls_dataplus to use imported gmt_now
old_sign_call = "    gmtnow = _gmt_now()"
new_sign_call = "    gmtnow = gmt_now()"
assert old_sign_call in content, "_gmt_now() call in _sign_nls_dataplus not found"
content = content.replace(old_sign_call, new_sign_call)
print("4. _sign_nls_dataplus updated to use imported gmt_now")

# 5. Remove _oss_sign function
old_oss_sign = """

def _oss_sign(
    method: str,
    ak_secret: str,
    date: str,
    content_type: str = "",
    content_md5: str = "",
    resource: str = "/",
) -> str:
    \"\"\"计算 OSS REST API 签名

    Args:
        method: HTTP 方法 (GET/PUT/HEAD)
        ak_secret: AccessKey Secret
        date: GMT 日期头
        content_type: Content-Type（PUT 时必填）
        content_md5: Content-MD5（有 body 时必填）
        resource: 规范化资源路径（如 /object_key，不含 bucket）
    \"\"\"
    string_to_sign = (
        f\"{method.upper()}\\n\"
        f\"{content_md5}\\n\"
        f\"{content_type}\\n\"
        f\"{date}\\n\"
        f\"{resource}\"
    )
    h = hmac.new(
        ak_secret.encode(\"utf-8\"),
        string_to_sign.encode(\"utf-8\"),
        hashlib.sha1,
    )
    return base64.b64encode(h.digest()).decode(\"utf-8\")"""

assert old_oss_sign in content, "_oss_sign not found"
content = content.replace(old_oss_sign, "")
print("5. _oss_sign removed")

# 6. Remove _oss_bucket_endpoint
old_endpoint = """

def _oss_bucket_endpoint(bucket: str, region: str) -> str:
    \"\"\"返回 bucket 级 OSS 域名\"\"\"
    return f\"{bucket}.oss-{region}.aliyuncs.com\""""

assert old_endpoint in content, "_oss_bucket_endpoint not found"
content = content.replace(old_endpoint, "")
print("6. _oss_bucket_endpoint removed")

# 7. Remove _ensure_bucket
old_ensure = """

def _ensure_bucket(bucket: str, region: str, ak_id: str, ak_secret: str) -> None:
    \"\"\"确保 OSS bucket 存在，不存在则创建

    使用 bucket 级域名（{bucket}.oss-{region}.aliyuncs.com），
    签名 resource 为 "/"。
    \"\"\"
    bucket_endpoint = _oss_bucket_endpoint(bucket, region)

    # ── 检查 bucket 是否存在 ──
    gmtnow = _gmt_now()
    sig = _oss_sign("HEAD", ak_secret, gmtnow, resource="/")

    resp = requests.head(
        f\"https://{bucket_endpoint}/\",
        headers={
            \"Date\": gmtnow,
            \"Authorization\": f\"OSS {ak_id}:{sig}\",
        },
        timeout=15,
    )

    if resp.status_code == 200:
        logger.info(f\"OSS Bucket 已存在: {bucket}\")
        return

    # ── Bucket 不存在，创建 ──
    logger.info(f\"创建 OSS Bucket: {bucket} ({region})\")
    gmtnow = _gmt_now()

    create_body = (
        '<?xml version=\"1.0\" encoding=\"UTF-8\"?>\\n'
        '<CreateBucketConfiguration>\\n'
        f'  <LocationConstraint>{region}</LocationConstraint>\\n'
        '</CreateBucketConfiguration>'
    )
    content_md5 = base64.b64encode(
        hashlib.md5(create_body.encode(\"utf-8\")).digest()
    ).decode(\"utf-8\")

    sig = _oss_sign(
        \"PUT\", ak_secret, gmtnow,
        content_type=\"application/xml\",
        content_md5=content_md5,
        resource=\"/\",
    )

    resp = requests.put(
        f\"https://{bucket_endpoint}/\",
        headers={
            \"Date\": gmtnow,
            \"Content-Type\": \"application/xml\",
            \"Content-MD5\": content_md5,
            \"Authorization\": f\"OSS {ak_id}:{sig}\",
        },
        data=create_body,
        timeout=15,
    )

    if resp.status_code in (200, 201, 409):
        logger.info(f\"OSS Bucket 就绪: {bucket}\")
    else:
        raise WhisperRuntimeError(
            \"创建 OSS Bucket 失败\",
            detail=f\"HTTP {resp.status_code}: {resp.text[:300]}\\n\"
                   f\"请确认 AccessKey 拥有 OSS 写入权限 (AliyunOSSFullAccess)\",
        )"""

assert old_ensure in content, "_ensure_bucket not found"
content = content.replace(old_ensure, "")
print("7. _ensure_bucket removed")

# 8. Remove _upload_to_oss
old_upload = """

def _upload_to_oss(
    local_path: Path,
    ak_id: str,
    ak_secret: str,
    settings: AppSettings,
) -> str:
    \"\"\"上传音频文件到阿里云 OSS 并返回公网 URL\"\"\"
    bucket = settings.alibaba.oss_bucket
    region = settings.alibaba.oss_region
    bucket_endpoint = _oss_bucket_endpoint(bucket, region)

    _ensure_bucket(bucket, region, ak_id, ak_secret)

    stem = local_path.stem
    suffix = local_path.suffix or \".m4a\"
    object_key = f\"audio-mind/{stem}{suffix}\"
    resource = f\"/{object_key}\"

    with open(local_path, \"rb\") as f:
        audio_data = f.read()

    content_type = _get_content_type(suffix)
    gmtnow = _gmt_now()
    sig = _oss_sign(\"PUT\", ak_secret, gmtnow, content_type=content_type, resource=resource)

    headers = {
        \"Date\": gmtnow,
        \"Content-Type\": content_type,
        \"Authorization\": f\"OSS {ak_id}:{sig}\",
    }

    size_mb = len(audio_data) / 1024 / 1024
    logger.info(f\"上传音频到 OSS: {bucket}/{object_key} ({size_mb:.1f}MB)\")

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.put(
                f\"https://{bucket_endpoint}/{object_key}\",
                headers=headers,
                data=audio_data,
                timeout=300,
            )
            if resp.status_code == 200:
                url = f\"https://{bucket_endpoint}/{object_key}\"
                logger.info(f\"OSS 上传完成: {url}\")
                return url
            else:
                logger.warning(
                    f\"第 {attempt}/{MAX_RETRIES} 次 OSS 上传失败: \"
                    f\"HTTP {resp.status_code} {resp.text[:200]}\"
                )
        except requests.RequestException as e:
            logger.warning(f\"第 {attempt}/{MAX_RETRIES} 次 OSS 上传网络错误: {e}\")

        if attempt < MAX_RETRIES:
            time.sleep(RETRY_BACKOFF * attempt)

    raise WhisperRuntimeError(
        \"OSS 上传失败\",
        detail=f\"重试 {MAX_RETRIES} 次后仍失败\",
    )"""

assert old_upload in content, "_upload_to_oss not found"
content = content.replace(old_upload, "")
print("8. _upload_to_oss removed")

# 9. Remove _get_content_type
old_ct = """

def _get_content_type(suffix: str) -> str:
    \"\"\"根据文件后缀返回 MIME type\"\"\"
    mapping = {
        \".m4a\": \"audio/mp4\",
        \".mp3\": \"audio/mpeg\",
        \".wav\": \"audio/wav\",
        \".flac\": \"audio/flac\",
        \".ogg\": \"audio/ogg\",
        \".aac\": \"audio/aac\",
        \".wma\": \"audio/x-ms-wma\",
    }
    return mapping.get(suffix.lower(), \"application/octet-stream\")"""

assert old_ct in content, "_get_content_type not found"
content = content.replace(old_ct, "")
print("9. _get_content_type removed")

# 10. Replace call site: _upload_to_oss(audio_path, ak_id, ak_secret, settings)
old_call = "oss_url = _upload_to_oss(audio_path, ak_id, ak_secret, settings)"
new_call = """ensure_bucket(settings.alibaba.oss_bucket, settings.alibaba.oss_region, ak_id, ak_secret)
        oss_url = upload_to_oss(
            audio_path, ak_id, ak_secret,
            settings.alibaba.oss_bucket, settings.alibaba.oss_region,
        )"""
assert old_call in content, "Call site not found in alibaba.py"
content = content.replace(old_call, new_call)
print("10. Call site updated in alibaba.py")

with open('src/transcriber/alibaba.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("DONE: alibaba.py saved")
