import os
import tempfile
import pytest
import yaml
from nimo.config import Config, ConfigError, LLMConfig, TapdConfig, TortoiseSvnConfig, SchedulesConfig, load_config


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


def test_missing_tapd_api_base_raises_error():
    yaml_content = """
llm:
  api_key: "sk-test"
  base_url: "https://api.deepseek.com"
  model: "deepseek-chat"
  max_tool_rounds: 5
  history_rounds: 10
tapd:
  access_token: "token"
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml_content)
        tmp_path = f.name
    try:
        with pytest.raises(ConfigError, match="配置文件缺少必填字段：tapd.api_base"):
            load_config(tmp_path)
    finally:
        os.unlink(tmp_path)


def test_schedules_config_default():
    sc = SchedulesConfig()
    assert sc.enabled is False


def test_schedules_config_enabled():
    sc = SchedulesConfig(enabled=True)
    assert sc.enabled is True


def test_load_config_without_schedules_section():
    """schedules 段缺失时使用默认值（enabled=False）。"""
    yaml_content = """llm:
  api_key: sk-test
  base_url: https://api.deepseek.com
  model: deepseek-chat
  max_tool_rounds: 5
  history_rounds: 10
tapd:
  api_base: https://api.tapd.cn
  access_token: token123
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml_content)
        tmp = f.name
    try:
        config = load_config(tmp)
        assert config.schedules.enabled is False
    finally:
        os.unlink(tmp)


def test_load_config_with_schedules_enabled():
    """schedules 段存在且 enabled 为 true。"""
    yaml_content = """llm:
  api_key: sk-test
  base_url: https://api.deepseek.com
  model: deepseek-chat
  max_tool_rounds: 5
  history_rounds: 10
tapd:
  api_base: https://api.tapd.cn
  access_token: token123
schedules:
  enabled: true
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml_content)
        tmp = f.name
    try:
        config = load_config(tmp)
        assert config.schedules.enabled is True
    finally:
        os.unlink(tmp)


def test_missing_tapd_access_token_raises_error():
    yaml_content = """
llm:
  api_key: "sk-test"
  base_url: "https://api.deepseek.com"
  model: "deepseek-chat"
  max_tool_rounds: 5
  history_rounds: 10
tapd:
  api_base: "https://api.tapd.cn"
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml_content)
        tmp_path = f.name
    try:
        with pytest.raises(ConfigError, match="配置文件缺少必填字段：tapd.access_token"):
            load_config(tmp_path)
    finally:
        os.unlink(tmp_path)
