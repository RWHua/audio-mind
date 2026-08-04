"""Fix volcengine.py: remove OSS functions, import from src.utils.oss"""
import re

with open('src/transcriber/volcengine.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Add import for upload_to_oss
old_import = """from src.exceptions import (
    AudioPreprocessError,
    WhisperRuntimeError,
    ConfigurationError,
)
from src.models import TranscriptResult, TranscriptSegment
from src.utils.config import get_settings, AppSettings
from src.utils.logger import setup_logger"""

new_import = """from src.exceptions import (
    AudioPreprocessError,
    WhisperRuntimeError,
    ConfigurationError,
)
from src.models import TranscriptResult, TranscriptSegment
from src.utils.config import get_settings, AppSettings
from src.utils.logger import setup_logger
from src.utils.oss import upload_to_oss"""

assert old_import in content, "Import block not found"
content = content.replace(old_import, new_import)
print("1. Import added")

# 2. Remove all OSS helper functions between "# ── OSS 上传辅助" and "# ── 说话人识别辅助" (or _identify_speakers)
# Strategy: find the section markers and remove everything between them
oss_start = content.find("# ── OSS 上传辅助 ────────────────────────────────────────")
speaker_start = content.find("def _identify_speakers(")

assert oss_start != -1, "OSS section start not found"
assert speaker_start != -1, "Speaker identify function not found"

# Remove everything from OSS constants through to just before _identify_speakers
oss_section = content[oss_start:speaker_start]
# Replace with a short comment
content = content.replace(oss_section, "# ── OSS 上传辅助 (委托给 src.utils.oss) ────────────────\n\n")
print("2. OSS functions removed")

# 3. Replace call site: _upload_to_oss(audio_path, settings)
old_call = "oss_url = _upload_to_oss(audio_path, settings)"
new_call = """oss_url = upload_to_oss(
                        audio_path,
                        settings.alibaba.access_key_id,
                        settings.alibaba.access_key_secret,
                        settings.alibaba.oss_bucket,
                        settings.alibaba.oss_region,
                    )"""
assert old_call in content, "Call site not found"
content = content.replace(old_call, new_call)
print("3. Call site updated")

# 4. Clean up unused imports (base64, hashlib, hmac are no longer needed for OSS in volcengine)
# Keep them - they won't cause issues and might be used elsewhere

with open('src/transcriber/volcengine.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("DONE: volcengine.py saved")
