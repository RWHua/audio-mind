"""完整流程：WAV→MP3→OSS上传→NLS文件识别→轮询结果"""
import os, hashlib, hmac, base64, urllib.parse, json, time, uuid, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path

import oss2
import requests
from dotenv import load_dotenv

# 修复 Windows GBK 编码问题
sys.stdout.reconfigure(encoding="utf-8")

load_dotenv()

AK_ID = os.environ["ALIBABA_ACCESS_KEY_ID"]
AK_SECRET = os.environ["ALIBABA_ACCESS_KEY_SECRET"]
APP_KEY = "SHLOHkq13r08iMmm"
BUCKET = "audio-mind-temp"
REGION = "cn-shanghai"
ENDPOINT_NLS = "filetrans.cn-shanghai.aliyuncs.com"
VERSION = "2018-08-17"

def percent_encode(s):
    return urllib.parse.quote(str(s), safe="~")

def sign_rpc(method, params, secret):
    sorted_params = sorted(params.items())
    canonical = "&".join(f"{percent_encode(k)}={percent_encode(str(v))}" for k, v in sorted_params)
    string_to_sign = f"{method.upper()}&{percent_encode('/')}&{percent_encode(canonical)}"
    key = (secret + "&").encode("utf-8")
    h = hmac.new(key, string_to_sign.encode("utf-8"), hashlib.sha1)
    return base64.b64encode(h.digest()).decode("utf-8")

# ── Step 1: 转换 WAV → 16kHz MP3 ──
print("=" * 60)
print("Step 1: 转换音频格式 (WAV → 16kHz MP3)")
wav_path = Path("temp_audio/E235_知行小酒馆.wav")
mp3_path = Path("temp_audio/E235_知行小酒馆_16k.mp3")

if not mp3_path.exists():
    cmd = [
        "ffmpeg", "-y",
        "-i", str(wav_path),
        "-ac", "1", "-ar", "16000", "-b:a", "64k",
        str(mp3_path),
    ]
    print("  ffmpeg 转换中...")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        print(f"  ❌ 转换失败: {result.stderr[-300:]}")
        sys.exit(1)
    size_mb = mp3_path.stat().st_size / 1024 / 1024
    print(f"  ✅ MP3 生成: {size_mb:.1f}MB")
else:
    size_mb = mp3_path.stat().st_size / 1024 / 1024
    print(f"  ✅ MP3 已存在: {size_mb:.1f}MB")

# ── Step 2: OSS 上传 ──
print("\n" + "=" * 60)
print("Step 2: 上传到 OSS")

# 使用 oss2 SDK
oss_endpoint = f"https://oss-{REGION}.aliyuncs.com"
auth = oss2.Auth(AK_ID, AK_SECRET)

# 确保 bucket 存在
bucket = oss2.Bucket(auth, oss_endpoint, BUCKET)
try:
    bucket.get_bucket_info()
    print(f"  Bucket 已存在: {BUCKET}")
except oss2.exceptions.NoSuchBucket:
    print(f"  创建 Bucket: {BUCKET} ({REGION})")
    bucket.create_bucket(oss2.BUCKET_ACL_PRIVATE, oss2.models.BucketCreateConfig(REGION))

# 上传文件
object_key = f"audio-mind/E235_16k.mp3"
print(f"  上传: {mp3_path} → {object_key}")

with open(mp3_path, "rb") as f:
    result = bucket.put_object(object_key, f)

if result.status == 200:
    # 生成公网 URL（1 小时有效期）
    public_url = bucket.sign_url("GET", object_key, 3600)
    print(f"  ✅ 上传成功!")
    print(f"  URL: {public_url[:80]}...")
else:
    print(f"  ❌ 上传失败: HTTP {result.status}")
    sys.exit(1)

# ── Step 3: 提交 NLS 识别任务 ──
print("\n" + "=" * 60)
print("Step 3: 提交 NLS 文件识别任务")

task_config = {
    "appkey": APP_KEY,
    "file_link": public_url,
    "enable_words": False,
}
task_json = json.dumps(task_config)

params = {
    "Format": "JSON",
    "Version": VERSION,
    "AccessKeyId": AK_ID,
    "SignatureMethod": "HMAC-SHA1",
    "Timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "SignatureVersion": "1.0",
    "SignatureNonce": str(uuid.uuid4()),
    "RegionId": "cn-shanghai",
    "Action": "SubmitTask",
    "Task": task_json,
}

sig = sign_rpc("POST", params, AK_SECRET)
params["Signature"] = sig

resp = requests.post(f"https://{ENDPOINT_NLS}/", data=params, timeout=30)
print(f"HTTP {resp.status_code}: {resp.text[:300]}")

if resp.status_code != 200:
    print("❌ 提交失败")
    sys.exit(1)

result_json = resp.json()
task_id = result_json.get("TaskId")
if not task_id:
    print(f"❌ 未获取到 TaskId")
    sys.exit(1)
print(f"✅ TaskId: {task_id}")

# ── Step 4: 轮询结果 ──
print("\n" + "=" * 60)
print("Step 4: 轮询识别结果")

for i in range(30):
    time.sleep(10)

    params = {
        "Format": "JSON",
        "Version": VERSION,
        "AccessKeyId": AK_ID,
        "SignatureMethod": "HMAC-SHA1",
        "Timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "SignatureVersion": "1.0",
        "SignatureNonce": str(uuid.uuid4()),
        "RegionId": "cn-shanghai",
        "Action": "GetTaskResult",
        "TaskId": task_id,
    }
    sig = sign_rpc("GET", params, AK_SECRET)
    params["Signature"] = sig
    qs = "&".join(f"{percent_encode(k)}={percent_encode(str(v))}" for k, v in params.items())

    resp = requests.get(f"https://{ENDPOINT_NLS}/?{qs}", timeout=30)
    result_json = resp.json()

    status = result_json.get("StatusText", "")
    code = result_json.get("StatusCode", 0)
    print(f"  Poll #{i+1}: Status={status} (Code={code})")

    if status == "SUCCESS":
        data = result_json.get("Data", result_json)
        text = data.get("Result", "")
        if not text:
            sentences = data.get("Sentences", [])
            text = "".join(s.get("Text", "") for s in sentences)
        print(f"\n✅ 转写完成! {len(text)} 字符")
        out_path = Path("output/test_transcript_16k.txt")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text, encoding="utf-8")
        print(f"已保存: {out_path}")
        print(f"\n前 300 字预览:\n{text[:300]}")
        break
    elif status == "FAILED":
        print(f"❌ 转写失败: {json.dumps(result_json, ensure_ascii=False, indent=2)}")
        break
    elif "UNSUPPORTED" in status:
        print(f"❌ 格式不支持: {status}")
        break
else:
    print("❌ 轮询超时")
