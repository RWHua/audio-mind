"""批量转写会议录音：上传 OSS → 火山引擎 → 保存文字稿"""
import sys
import time
from pathlib import Path

# 项目路径
PROJECT = Path(r"D:\vibecoding\project\Agents\audio-mind")
sys.path.insert(0, str(PROJECT / "src"))

from src.transcriber.volcengine import transcribe_volcengine
from src.utils.config import get_settings
from src.utils.oss import upload_to_oss

AUDIO_DIR = Path(r"D:\knowledge\newKnowledge\工作Agent\Day\0713\会议录音")
OUTPUT_DIR = AUDIO_DIR / "transcripts"
OUTPUT_DIR.mkdir(exist_ok=True)

FILES = sorted(AUDIO_DIR.glob("*.m4a"))

settings = get_settings()

for i, fpath in enumerate(FILES, 1):
    name = fpath.stem
    out_path = OUTPUT_DIR / f"{name}.md"
    
    if out_path.exists():
        print(f"[{i}/{len(FILES)}] ⏭️ {name} — 已存在，跳过")
        continue
    
    print(f"\n{'='*60}")
    print(f"[{i}/{len(FILES)}] 📤 {name}")
    print(f"  文件大小: {fpath.stat().st_size / 1024 / 1024:.1f} MB")
    
    # Step 1: 上传 OSS
    t0 = time.time()
    print("  ↑ 上传到 OSS...")
    try:
        oss_url = upload_to_oss(
            fpath,
            settings.alibaba.access_key_id,
            settings.alibaba.access_key_secret,
            settings.alibaba.oss_bucket,
            settings.alibaba.oss_region,
        )
        print(f"  ✅ 上传完成 ({time.time()-t0:.0f}s)")
        print(f"     OSS URL: {oss_url[:80]}...")
    except Exception as e:
        print(f"  ❌ OSS 上传失败: {e}")
        continue
    
    # Step 2: 火山引擎转写
    t1 = time.time()
    print("  🎤 提交转写...")
    try:
        result = transcribe_volcengine(
            audio_path=fpath,
            settings=settings,
            public_url=oss_url,
            episode_info=name,
        )
        elapsed = time.time() - t1
        print(f"  ✅ 转写完成 ({elapsed:.0f}s, {len(result.full_text)} 字符)")
    except Exception as e:
        print(f"  ❌ 转写失败: {e}")
        continue
    
    # Step 3: 保存
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"# {name}\n\n")
        f.write(f"> 转写时间: {time.strftime('%Y-%m-%d %H:%M')}\n")
        f.write(f"> 文件大小: {fpath.stat().st_size / 1024 / 1024:.1f} MB\n")
        f.write(f"> 字符数: {len(result.full_text)}\n\n")
        f.write("---\n\n")
        f.write(result.full_text)
    
    print(f"  📝 已保存: {out_path.name}")
    print(f"  ⏱️ 本文件总耗时: {time.time()-t0:.0f}s")

print("\n" + "="*60)
print(f"🎉 全部完成！共处理 {len(FILES)} 个文件")
print(f"   输出目录: {OUTPUT_DIR}")
