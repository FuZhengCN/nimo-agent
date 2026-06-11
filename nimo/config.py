import os
import yaml
from dataclasses import dataclass


class ConfigError(Exception):
    pass


@dataclass
class LLMConfig:
    api_key: str
    base_url: str
    model: str
    max_tool_rounds: int
    history_rounds: int
    temperature: float = 0.3
    history_persist: bool = False
    history_summarize: bool = False
    profile_extract: bool = False


@dataclass
class TapdConfig:
    api_base: str
    access_token: str
    nick: str = ""
    company_id: str = ""
    owner: str = ""


@dataclass
class Config:
    llm: LLMConfig
    tapd: TapdConfig


def _env_override(key: str, default: str) -> str:
    env_key = key.upper().replace(".", "_")
    return os.environ.get(env_key, default)


def load_config(path: str = "config.yaml") -> Config:
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
    except FileNotFoundError:
        raise ConfigError(f"配置文件未找到：{path}")
    except yaml.YAMLError as e:
        raise ConfigError(f"配置文件 YAML 格式错误 {path}：{e}")

    for section in ["llm", "tapd"]:
        if section not in raw:
            raise ConfigError(f"配置文件缺少必填段：{section}")

    required_llm_fields = ["api_key", "base_url", "model", "max_tool_rounds", "history_rounds"]
    for field in required_llm_fields:
        if field not in raw["llm"]:
            raise ConfigError(f"配置文件缺少必填字段：llm.{field}")

    tapd_raw = raw["tapd"]
    for field in ["api_base", "access_token"]:
        if field not in tapd_raw:
            raise ConfigError(f"配置文件缺少必填字段：tapd.{field}")

    llm = LLMConfig(
        api_key=_env_override("llm.api_key", raw["llm"]["api_key"]),
        base_url=raw["llm"]["base_url"],
        model=raw["llm"]["model"],
        max_tool_rounds=raw["llm"]["max_tool_rounds"],
        history_rounds=raw["llm"]["history_rounds"],
        temperature=raw["llm"].get("temperature", 0.3),
        history_persist=raw["llm"].get("history_persist", False),
        history_summarize=raw["llm"].get("history_summarize", False),
        profile_extract=raw["llm"].get("profile_extract", False),
    )
    tapd = TapdConfig(
        api_base=tapd_raw["api_base"],
        access_token=_env_override("tapd.access_token", tapd_raw["access_token"]),
        nick=tapd_raw.get("nick", ""),
        company_id=tapd_raw.get("company_id", ""),
        owner=tapd_raw.get("owner", ""),
    )
    return Config(llm=llm, tapd=tapd)
