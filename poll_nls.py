"""轮询 NLS CDN 直传转写任务"""
import os, hashlib, hmac, base64, urllib.parse, json, uuid, requests, time, sys
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8")
load_dotenv()

AK_ID = os.environ["ALIBABA_ACCESS_KEY_ID"]
AK_SECRET = os.environ["ALIBABA_ACCESS_KEY_SECRET"]
TASK_ID = "8c22dbd89ca749f99915f8bff870d8d2"
ENDPOINT = "filetrans.cn-shanghai.aliyuncs.com"
VERSION = "2018-08-17"

def percent_encode(s):
    return urllib.parse.quote(str(s), safe="~")

def sign_rpc(method, params, secret):
    sorted_params = sorted(params.items())
    canonical = "&".join(f"{percent_encode(k)}={percent_encode(str(v))}" for k, v in sorted_params)
    string_to_sign = method.upper() + "&" + percent_encode("/") + "&" + percent_encode(canonical)
    key = (secret + "&").encode("utf-8")
    h = hmac.new(key, string_to_sign.encode("utf-8"), hashlib.sha1)
    return base64.b64encode(h.digest()).decode("utf-8")

print(f"轮询 TaskId: {TASK_ID}")
for i in range(30):
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
        "TaskId": TASK_ID,
    }
    sig = sign_rpc("GET", params, AK_SECRET)
    params["Signature"] = sig
    qs = "&".join(f"{percent_encode(k)}={percent_encode(str(v))}" for k, v in params.items())

    resp = requests.get(f"https://{ENDPOINT}/?{qs}", timeout=30)
    result = resp.json()

    status = result.get("StatusText", "")
    code = result.get("StatusCode", 0)
    print(f"  Poll #{i+1}: Status={status} (Code={code})")

    if status == "SUCCESS":
        data = result.get("Data", result)
        text = data.get("Result", "")
        if not text:
            sentences = data.get("Sentences", [])
            text = "".join(s.get("Text", "") for s in sentences)
        print(f"\n✅ 转写完成! {len(text)} 字符")
        out_path = Path("output/test_transcript_nls_cdn.txt")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text, encoding="utf-8")
        print(f"已保存: {out_path}")
        print(f"\n前 500 字预览:\n{text[:500]}")
        break
    elif status == "FAILED":
        print(f"❌ 转写失败: {json.dumps(result, ensure_ascii=False, indent=2)[:500]}")
        break
    else:
        time.sleep(10)
else:
    print("❌ 轮询超时")
