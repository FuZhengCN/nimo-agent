import os
import tempfile
import pytest
import yaml
from nimo.config import Config, ConfigError, LLMConfig, TapdConfig, load_config


def test_load_config_from_yaml():
    yaml_content = """
llm:
  api_key: "sk-test"
  base_url: "https://api.deepseek.com"
  model: "deepseek-chat"
  max_tool_rounds: 5
  history_rounds: 10
tapd:
  api_base: "https://api.tapd.cn"
  access_token: "token123"
  nick: "testuser"
  company_id: "12345"
  owner: "testuser"
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml_content)
        tmp_path = f.name

    try:
        config = load_config(tmp_path)
        assert config.llm.api_key == "sk-test"
        assert config.llm.model == "deepseek-chat"
        assert config.llm.max_tool_rounds == 5
        assert config.llm.history_rounds == 10
        assert config.tapd.api_base == "https://api.tapd.cn"
        assert config.tapd.access_token == "token123"
        assert config.tapd.nick == "testuser"
    finally:
        os.unlink(tmp_path)


def test_env_var_override():
    yaml_content = """
llm:
  api_key: "sk-from-yaml"
  base_url: "https://api.deepseek.com"
  model: "deepseek-chat"
  max_tool_rounds: 5
  history_rounds: 10
tapd:
  api_base: "https://api.tapd.cn"
  access_token: "token-yaml"
  nick: "yaml-user"
  company_id: "111"
  owner: "yaml-user"
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml_content)
        tmp_path = f.name

    try:
        os.environ["LLM_API_KEY"] = "sk-from-env"
        os.environ["TAPD_ACCESS_TOKEN"] = "token-env"
        config = load_config(tmp_path)
        assert config.llm.api_key == "sk-from-env"
        assert config.tapd.access_token == "token-env"
    finally:
        os.unlink(tmp_path)
        del os.environ["LLM_API_KEY"]
        del os.environ["TAPD_ACCESS_TOKEN"]


def test_missing_file_raises_error():
    with pytest.raises(ConfigError, match="配置文件未找到"):
        load_config("nonexistent_xyz.yaml")


def test_malformed_yaml_raises_error():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write("llm: [unclosed list\n")
        tmp_path = f.name
    try:
        with pytest.raises(ConfigError, match="配置文件 YAML 格式错误"):
            load_config(tmp_path)
    finally:
        os.unlink(tmp_path)


def test_missing_section_raises_error():
    yaml_content = """
llm:
  api_key: "sk-test"
  base_url: "https://api.deepseek.com"
  model: "deepseek-chat"
  max_tool_rounds: 5
  history_rounds: 10
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml_content)
        tmp_path = f.name
    try:
        with pytest.raises(ConfigError, match="配置文件缺少必填段"):
            load_config(tmp_path)
    finally:
        os.unlink(tmp_path)
