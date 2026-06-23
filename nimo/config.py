import os
import yaml
from dataclasses import dataclass, field
from pathlib import Path


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
class TortoiseSvnConfig:
    paths: dict[str, str] = field(default_factory=dict)  # 项目名 → 工作副本路径


@dataclass
class SchedulesConfig:
    enabled: bool = False


@dataclass
class Config:
    llm: LLMConfig
    tapd: TapdConfig
    tortoisesvn: TortoiseSvnConfig = field(default_factory=TortoiseSvnConfig)
    schedules: SchedulesConfig = field(default_factory=SchedulesConfig)


def _env_override(key: str, default: str) -> str:
    env_key = key.upper().replace(".", "_")
    return os.environ.get(env_key, default)


def _resolve_config_path(path: str | None) -> str:
    """解析配置文件路径。

    优先级：
    1. 显式传入的 path → 直接使用
    2. NIMO_CONFIG 环境变量 → 直接使用
    3. 默认值 → 包目录下的 config.yaml（不随 CWD 变化）
    """
    if path is not None:
        return path
    env_path = os.environ.get("NIMO_CONFIG")
    if env_path:
        return env_path
    pkg_root = Path(__file__).resolve().parent.parent
    return str(pkg_root / "config.yaml")


def load_config(path: str | None = None) -> Config:
    import logging
    logger = logging.getLogger(__name__)
    resolved = _resolve_config_path(path)
    try:
        with open(resolved, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        logger.info("已加载配置：%s", os.path.abspath(resolved))
    except FileNotFoundError:
        raise ConfigError(f"配置文件未找到：{resolved}")
    except yaml.YAMLError as e:
        raise ConfigError(f"配置文件 YAML 格式错误 {resolved}：{e}")

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
    ts_raw = raw.get("tortoisesvn", {})
    paths = ts_raw.get("paths", {})
    # 兼容旧字段 wc_path
    if "wc_path" in ts_raw and not paths:
        paths["default"] = ts_raw["wc_path"]
    tortoisesvn = TortoiseSvnConfig(paths=paths)
    schedules_raw = raw.get("schedules", {})
    schedules = SchedulesConfig(
        enabled=schedules_raw.get("enabled", False),
    )
    logger.info("定时功能：%s", "已启用" if schedules.enabled else "未启用（schedules.enabled=false）")
    return Config(llm=llm, tapd=tapd, tortoisesvn=tortoisesvn, schedules=schedules)
