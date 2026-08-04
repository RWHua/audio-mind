"""单独转写需求串讲4"""
import sys, time
from pathlib import Path

PROJECT = Path(r"D:\vibecoding\project\Agents\audio-mind")
sys.path.insert(0, str(PROJECT / "src"))

from src.transcriber.volcengine import transcribe_volcengine
from src.utils.config import get_settings
from src.utils.oss import upload_to_oss

fpath = Path(r"D:\knowledge\newKnowledge\项目0713\会议录音及转写\会议录音\需求串讲 4.m4a")
name = fpath.stem
settings = get_settings()

print(f"📤 {name} ({fpath.stat().st_size/1024/1024:.0f} MB)")
t0 = time.time()

print("↑ 上传 OSS...")
oss_url = upload_to_oss(fpath,
    settings.alibaba.access_key_id, settings.alibaba.access_key_secret,
    settings.alibaba.oss_bucket, settings.alibaba.oss_region)
print(f"✅ 上传完成 ({time.time()-t0:.0f}s)")

t1 = time.time()
print("🎤 转写中...")
result = transcribe_volcengine(audio_path=fpath, settings=settings, public_url=oss_url, episode_info=name)
print(f"✅ 转写完成 ({time.time()-t1:.0f}s, {len(result.full_text)} 字符)")

out = Path(r"D:\knowledge\newKnowledge\项目0713\会议录音及转写\转写") / f"{name}.md"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(f"# {name}\n\n> 转写时间: {time.strftime('%Y-%m-%d %H:%M')}\n> 文件大小: {fpath.stat().st_size/1024/1024:.0f} MB\n> 字符数: {len(result.full_text)}\n\n---\n\n{result.full_text}", encoding="utf-8")
print(f"📝 已保存: {out}\n⏱️ 总耗时: {time.time()-t0:.0f}s")
