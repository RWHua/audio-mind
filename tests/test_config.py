"""测试配置加载模块：get_settings、环境变量解析"""

import os
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from src.utils.config import get_settings, AppSettings, _resolve_env


class TestResolveEnv:
    """环境变量解析测试"""

    def test_plain_string_no_var(self):
        """纯字符串不含变量引用"""
        assert _resolve_env("hello") == "hello"
        assert _resolve_env("https://api.deepseek.com") == "https://api.deepseek.com"

    def test_var_with_default(self):
        """${VAR:-default} 格式 — 变量存在时使用变量值"""
        with patch.dict(os.environ, {"MY_VAR": "from_env"}, clear=False):
            assert _resolve_env("${MY_VAR:-fallback}") == "from_env"

    def test_var_with_default_fallback(self):
        """${VAR:-default} 格式 — 变量不存在时使用默认值"""
        with patch.dict(os.environ, {}, clear=True):
            # 确保变量不存在
            os.environ.pop("NONEXISTENT_VAR", None)
            assert _resolve_env("${NONEXISTENT_VAR:-fallback_value}") == "fallback_value"

    def test_var_without_default_missing(self):
        """${VAR} 格式 — 变量不存在时返回空字符串"""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("MISSING_VAR", None)
            assert _resolve_env("${MISSING_VAR}") == ""

    def test_var_empty_default(self):
        """${VAR:-} — 空默认值"""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("EMPTY_VAR", None)
            assert _resolve_env("${EMPTY_VAR:-}") == ""


class TestGetSettings:
    """get_settings() 加载测试"""

    def test_default_settings(self, tmp_path):
        """无配置文件时使用默认值"""
        # 创建空的 settings.yaml
        config_path = tmp_path / "settings.yaml"
        config_path.write_text("{}", encoding="utf-8")

        with patch.dict(os.environ, {}, clear=True):
            settings = get_settings(str(config_path))
            assert isinstance(settings, AppSettings)
            assert settings.transcriber.provider == "whisper"
            assert settings.whisper.model == "medium"

    def test_settings_from_yaml(self, tmp_path):
        """从 YAML 加载配置"""
        config_path = tmp_path / "settings.yaml"
        config_path.write_text(
            yaml.dump({
                "transcriber": {"provider": "volcengine"},
                "whisper": {"model": "large-v3"},
            }),
            encoding="utf-8",
        )

        with patch.dict(os.environ, {}, clear=True):
            settings = get_settings(str(config_path))
            assert settings.transcriber.provider == "volcengine"
            assert settings.whisper.model == "large-v3"

    def test_env_var_injection(self, tmp_path):
        """环境变量注入优先于 YAML"""
        config_path = tmp_path / "settings.yaml"
        config_path.write_text("{}", encoding="utf-8")

        with patch.dict(os.environ, {
            "DEEPSEEK_API_KEY": "sk-test-key",
        }, clear=False):
            settings = get_settings(str(config_path))
            assert settings.deepseek.api_key == "sk-test-key"

    def test_env_var_resolution_in_yaml(self, tmp_path):
        """YAML 中的 ${VAR:-default} 被解析"""
        config_path = tmp_path / "settings.yaml"
        config_path.write_text(
            yaml.dump({
                "deepseek": {
                    "base_url": "${TEST_BASE_URL:-https://default.api.com}",
                },
            }),
            encoding="utf-8",
        )

        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("TEST_BASE_URL", None)
            settings = get_settings(str(config_path))
            assert settings.deepseek.base_url == "https://default.api.com"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
