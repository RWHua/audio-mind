"""单独补转文件5（需求串讲3）"""
import sys, time
from pathlib import Path

PROJECT = Path(r"D:\vibecoding\project\Agents\audio-mind")
sys.path.insert(0, str(PROJECT / "src"))

from src.transcriber.volcengine import transcribe_volcengine
from src.utils.config import get_settings
from src.utils.oss import upload_to_oss

fpath = Path(r"D:\knowledge\newKnowledge\工作Agent\Day\0713\会议录音\需求串讲3-System Checklist说明.m4a")
name = fpath.stem
settings = get_settings()

print(f"📤 {name} ({fpath.stat().st_size/1024/1024:.0f} MB)")
t0 = time.time()

# Upload OSS
print("↑ 上传 OSS...")
oss_url = upload_to_oss(
    fpath,
    settings.alibaba.access_key_id,
    settings.alibaba.access_key_secret,
    settings.alibaba.oss_bucket,
    settings.alibaba.oss_region,
)
print(f"✅ 上传完成 ({time.time()-t0:.0f}s)")

# Transcribe
t1 = time.time()
print("🎤 转写中（约 2.9h 音频，预计 15-20min）...")
result = transcribe_volcengine(
    audio_path=fpath,
    settings=settings,
    public_url=oss_url,
    episode_info=name,
)
elapsed = time.time() - t1
print(f"✅ 转写完成 ({elapsed:.0f}s, {len(result.full_text)} 字符)")

# Save
out_dir = Path(r"D:\knowledge\newKnowledge\项目0713\会议录音及转写\转写")
out_dir.mkdir(parents=True, exist_ok=True)
out_path = out_dir / f"{name}.md"
with open(out_path, "w", encoding="utf-8") as f:
    f.write(f"# {name}\n\n")
    f.write(f"> 转写时间: {time.strftime('%Y-%m-%d %H:%M')}\n")
    f.write(f"> 文件大小: {fpath.stat().st_size / 1024 / 1024:.0f} MB\n")
    f.write(f"> 字符数: {len(result.full_text)}\n\n")
    f.write("---\n\n")
    f.write(result.full_text)

print(f"📝 已保存: {out_path}")
print(f"⏱️ 总耗时: {time.time()-t0:.0f}s")
