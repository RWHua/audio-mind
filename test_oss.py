"""测试 OSS 上传（用正确的设置）"""
import os, hashlib, hmac, base64, hashlib
from datetime import datetime, timezone
import requests
from dotenv import load_dotenv
from pathlib import Path

load_dotenv()

AK_ID = os.environ["ALIBABA_ACCESS_KEY_ID"]
AK_SECRET = os.environ["ALIBABA_ACCESS_KEY_SECRET"]

_WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

def gmt_now():
    now = datetime.now(timezone.utc)
    return f"{_WEEKDAYS[now.weekday()]}, {now.day:02d} {_MONTHS[now.month - 1]} {now.year} {now.hour:02d}:{now.minute:02d}:{now.second:02d} GMT"

def oss_sign(method, secret, date, content_type="", content_md5="", resource="/"):
    string_to_sign = f"{method.upper()}\n{content_md5}\n{content_type}\n{date}\n{resource}"
    print(f"OSS StringToSign: {repr(string_to_sign)}")
    h = hmac.new(secret.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha1)
    return base64.b64encode(h.digest()).decode("utf-8")

BUCKET = "audio-mind-temp"
REGION = "cn-shanghai"
ENDPOINT = f"{BUCKET}.oss-{REGION}.aliyuncs.com"

# Test 1: HEAD bucket (check exists)
print("=" * 60)
print("Test 1: HEAD bucket check")
date = gmt_now()
sig = oss_sign("HEAD", AK_SECRET, date, resource="/")
headers = {"Date": date, "Authorization": f"OSS {AK_ID}:{sig}"}
print(f"Endpoint: {ENDPOINT}")
print(f"Date: {date}")
resp = requests.head(f"https://{ENDPOINT}/", headers=headers, timeout=15)
print(f"HTTP {resp.status_code}")
print(f"Response headers: {dict(resp.headers)}")

# Test 2: PUT create bucket
print("\n" + "=" * 60)
print("Test 2: PUT create bucket")
date = gmt_now()
create_body = '<?xml version="1.0" encoding="UTF-8"?>\n<CreateBucketConfiguration>\n  <LocationConstraint>cn-shanghai</LocationConstraint>\n</CreateBucketConfiguration>'
content_md5 = base64.b64encode(hashlib.md5(create_body.encode("utf-8")).digest()).decode("utf-8")
sig = oss_sign("PUT", AK_SECRET, date, content_type="application/xml", content_md5=content_md5, resource="/")
headers = {
    "Date": date,
    "Content-Type": "application/xml",
    "Content-MD5": content_md5,
    "Authorization": f"OSS {AK_ID}:{sig}",
}
resp = requests.put(f"https://{ENDPOINT}/", headers=headers, data=create_body, timeout=15)
print(f"HTTP {resp.status_code}")
print(f"Response: {resp.text[:500]}")
print(f"Request ID: {resp.headers.get('x-oss-request-id')}")

# Test 3: PUT small test object if bucket exists
if resp.status_code in (200, 201, 409):
    print("\n" + "=" * 60)
    print("Test 3: Upload test file to OSS")
    test_path = Path("temp_audio/E235_知行小酒馆.m4a")
    if test_path.exists():
        size_mb = test_path.stat().st_size / 1024 / 1024
        print(f"File: {test_path} ({size_mb:.1f}MB)")

        with open(test_path, "rb") as f:
            data = f.read()

        object_key = "test/audio.m4a"
        date = gmt_now()
        sig = oss_sign("PUT", AK_SECRET, date, content_type="audio/mp4", resource=f"/{object_key}")
        headers = {
            "Date": date,
            "Content-Type": "audio/mp4",
            "Authorization": f"OSS {AK_ID}:{sig}",
        }
        resp = requests.put(f"https://{ENDPOINT}/{object_key}", headers=headers, data=data, timeout=120)
        print(f"HTTP {resp.status_code}")
        print(f"Response: {resp.text[:300]}")
        if resp.status_code == 200:
            url = f"https://{ENDPOINT}/{object_key}"
            print(f"✅ 上传成功! URL: {url}")
    else:
        print("File not found, skipping")
