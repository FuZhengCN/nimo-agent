"""技能注册中心：发现、激活、脚本执行。"""
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nimo.tools.registry import ToolResult

logger = logging.getLogger(__name__)


@dataclass
class SkillMeta:
    name: str
    description: str = ""
    instructions: str = ""
    keywords: list[str] = field(default_factory=list)
    scripts: list[str] = field(default_factory=list)
    root_dir: str = ""


class SkillRegistry:
    _instance: "SkillRegistry | None" = None

    def __init__(self):
        self._skills: dict[str, SkillMeta] = {}
        self._active_instructions: str | None = None

    @classmethod
    def get_instance(cls) -> "SkillRegistry":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        cls._instance = None

    def list_meta(self) -> list[dict[str, Any]]:
        return [
            {
                "name": m.name,
                "description": m.description,
                "keywords": m.keywords,
            }
            for m in self._skills.values()
        ]

    def get_active_instructions(self) -> str | None:
        return self._active_instructions
