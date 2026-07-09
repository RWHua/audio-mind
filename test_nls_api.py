"""轮询 GetTaskResult 获取转写文本"""
import os, hashlib, hmac, base64, urllib.parse, json, time, uuid
from datetime import datetime, timezone
import requests
from dotenv import load_dotenv

load_dotenv()

AK_ID = os.environ["ALIBABA_ACCESS_KEY_ID"]
AK_SECRET = os.environ["ALIBABA_ACCESS_KEY_SECRET"]
TASK_ID = "f06b41f87ea04239be0c8f2f2a403df7"
ENDPOINT = "filetrans.cn-shanghai.aliyuncs.com"
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

def get_result():
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
    return resp

for i in range(20):
    print(f"\nPoll #{i+1}...")
    resp = get_result()
    print(f"HTTP {resp.status_code}")
    result = resp.json()
    print(json.dumps(result, ensure_ascii=False, indent=2)[:500])

    status = result.get("StatusText", "")
    if status == "SUCCESS":
        data = result.get("Data", result)
        text = data.get("Result", "")
        if text:
            print(f"\n✅ 转写完成! {len(text)} 字符")
            # Save to file
            with open("test_transcript.txt", "w", encoding="utf-8") as f:
                f.write(text)
            print(f"已保存到 test_transcript.txt")
        break
    elif status == "FAILED":
        print("❌ 转写失败")
        break
    elif status == "RUNNING":
        time.sleep(10)
    else:
        # Maybe already done? StatusText might be different
        # Try checking Data.Result directly
        data = result.get("Data", result)
        text = data.get("Result", "")
        if text:
            print(f"\n✅ 直接获取到结果! {len(text)} 字符")
            with open("test_transcript.txt", "w", encoding="utf-8") as f:
                f.write(text)
            print("已保存到 test_transcript.txt")
            break
        # Check for sentences array
        sentences = data.get("Sentences", [])
        if sentences:
            print(f"📝 获取到 {len(sentences)} 个句子")
            full = "".join(s.get("Text", "") for s in sentences)
            with open("test_transcript.txt", "w", encoding="utf-8") as f:
                f.write(full)
            print(f"合并: {len(full)} 字符")
            break
        time.sleep(10)
