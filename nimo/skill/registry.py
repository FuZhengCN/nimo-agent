"""技能注册中心：发现、激活、脚本执行。"""
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

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

    def activate(self, name: str) -> str:
        meta = self._skills.get(name)
        if meta is None:
            raise ValueError(f"未找到技能：{name}，可用：{', '.join(self._skills.keys())}")
        self._active_instructions = meta.instructions
        script_list = ", ".join(meta.scripts) if meta.scripts else "无"
        return f"已激活技能「{meta.name}」：{meta.description[:120]}。可用脚本：{script_list}"

    def deactivate(self) -> None:
        self._active_instructions = None

    async def run_script(self, name: str, script: str, args: list[str]) -> ToolResult:
        import asyncio
        import sys

        meta = self._skills.get(name)
        if meta is None:
            return ToolResult(success=False, error=f"未找到技能：{name}")
        if script not in meta.scripts:
            return ToolResult(
                success=False,
                error=f"脚本不在白名单中：{script}，可用：{', '.join(meta.scripts) or '无'}",
            )
        if ".." in script.replace("\\", "/"):
            return ToolResult(success=False, error=f"脚本路径包含路径遍历：{script}")

        script_path = Path(meta.root_dir) / script
        if not script_path.is_file():
            return ToolResult(success=False, error=f"脚本文件不存在：{script_path}")

        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, str(script_path), *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=meta.root_dir,
                env={},
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
        except asyncio.TimeoutError:
            return ToolResult(success=False, error="脚本执行超时（120s）")
        except FileNotFoundError:
            return ToolResult(success=False, error=f"Python 未找到：{sys.executable}")
        except Exception as e:
            return ToolResult(success=False, error=str(e))

        out_str = stdout.decode(errors="replace").strip()
        err_str = stderr.decode(errors="replace").strip()
        if proc.returncode != 0:
            return ToolResult(success=False, error=err_str or out_str or f"脚本返回非零退出码 {proc.returncode}")
        return ToolResult(success=True, data=out_str)

    def discover(self, skills_dir: str) -> int:
        root = Path(skills_dir)
        if not root.is_dir():
            logger.info("技能目录不存在：%s", root)
            return 0
        count = 0
        for entry in sorted(root.iterdir()):
            if not entry.is_dir():
                continue
            meta = (
                self._try_skill_yml(entry)
                or self._try_skill_md_frontmatter(entry)
                or self._fallback_minimal(entry)
            )
            if meta:
                self._skills[meta.name] = meta
                count += 1
                logger.info("发现技能：%s (%s)", meta.name, entry)
        return count

    def _try_skill_yml(self, dir_: Path) -> SkillMeta | None:
        yml_path = dir_ / "skill.yml"
        if not yml_path.is_file():
            return None
        try:
            with open(yml_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except Exception:
            logger.warning("skill.yml 解析失败: %s", yml_path, exc_info=True)
            return None
        if not isinstance(data, dict) or "name" not in data:
            return None

        name = data["name"]
        description = data.get("description", "")
        instructions_file = data.get("instructions_file", "SKILL.md")
        instructions_path = dir_ / instructions_file
        instructions = ""
        if instructions_path.is_file():
            instructions = instructions_path.read_text(encoding="utf-8")

        keywords = data.get("keywords", [])
        if isinstance(keywords, str):
            keywords = [k.strip() for k in keywords.split(",")]

        scripts = data.get("scripts", [])
        if not isinstance(scripts, list):
            scripts = []
        if not scripts:
            scripts = self._scan_scripts(dir_)

        return SkillMeta(
            name=name, description=description, instructions=instructions,
            keywords=keywords, scripts=scripts, root_dir=str(dir_),
        )

    def _try_skill_md_frontmatter(self, dir_: Path) -> SkillMeta | None:
        md_path = dir_ / "SKILL.md"
        if not md_path.is_file():
            return None
        content = md_path.read_text(encoding="utf-8")
        if not content.startswith("---"):
            return None
        end = content.find("---", 3)
        if end == -1:
            return None
        try:
            frontmatter = yaml.safe_load(content[3:end])
        except Exception:
            logger.warning("SKILL.md frontmatter 解析失败: %s", md_path, exc_info=True)
            return None
        if not isinstance(frontmatter, dict) or "name" not in frontmatter:
            return None

        name = frontmatter["name"]
        description = frontmatter.get("description", "")
        instructions = content[end + 3:].strip()

        keywords = frontmatter.get("keywords", [])
        if isinstance(keywords, str):
            keywords = [k.strip() for k in keywords.split(",")]

        scripts = self._scan_scripts(dir_)

        return SkillMeta(
            name=name, description=description, instructions=instructions,
            keywords=keywords, scripts=scripts, root_dir=str(dir_),
        )

    def _fallback_minimal(self, dir_: Path) -> SkillMeta:
        name = dir_.name
        description = ""
        instructions = ""
        readme = dir_ / "README.md"
        if readme.is_file():
            instructions = readme.read_text(encoding="utf-8")
        else:
            md_files = list(dir_.glob("*.md"))
            if md_files:
                instructions = md_files[0].read_text(encoding="utf-8")

        scripts = self._scan_scripts(dir_)

        return SkillMeta(
            name=name, description=description, instructions=instructions,
            keywords=[], scripts=scripts, root_dir=str(dir_),
        )

    def _scan_scripts(self, dir_: Path) -> list[str]:
        scripts_dir = dir_ / "scripts"
        if not scripts_dir.is_dir():
            return []
        return [
            str(p.relative_to(dir_))
            for p in sorted(scripts_dir.rglob("*.py"))
        ]
