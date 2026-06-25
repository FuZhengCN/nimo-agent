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
    sections: dict[str, str] = field(default_factory=dict)


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
                "sections": [k for k in m.sections if not k.startswith("_")],
            }
            for m in self._skills.values()
        ]

    def get_active_instructions(self) -> str | None:
        return self._active_instructions

    def get_section_toc(self, name: str) -> list[str]:
        """返回指定技能的章节标题列表（不含 _preface）。"""
        meta = self._skills.get(name)
        if meta is None:
            return []
        return [k for k in meta.sections if not k.startswith("_")]

    def activate(self, name: str, sections: list[str] | None = None) -> str:
        meta = self._skills.get(name)
        if meta is None:
            raise ValueError(f"未找到技能：{name}，可用：{', '.join(self._skills.keys())}")
        if sections and meta.sections:
            parts = []
            if "_preface" in meta.sections:
                parts.append(meta.sections["_preface"])
            for s in sections:
                if s in meta.sections:
                    parts.append(f"## {s}\n\n{meta.sections[s]}")
            self._active_instructions = "\n\n".join(parts) if parts else meta.instructions
        else:
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
        return count

    def _try_skill_yml(self, dir_: Path) -> SkillMeta | None:
        yml_path = dir_ / "skill.yml"
        if not yml_path.is_file():
            return None
        try:
            with open(yml_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except FileNotFoundError:
            return None
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
            try:
                instructions = instructions_path.read_text(encoding="utf-8")
            except Exception:
                logger.warning("指令文件读取失败: %s", instructions_path, exc_info=True)

        keywords = data.get("keywords", [])
        if isinstance(keywords, str):
            keywords = [k.strip() for k in keywords.split(",")]

        scripts = data.get("scripts", [])
        if not isinstance(scripts, list):
            scripts = []
        if not scripts:
            scripts = self._scan_scripts(dir_)

        sections = self._parse_sections(instructions)
        keywords = self._enrich_keywords(keywords, sections)
        return SkillMeta(
            name=name, description=description, instructions=instructions,
            keywords=keywords, scripts=scripts, root_dir=str(dir_),
            sections=sections,
        )

    def _try_skill_md_frontmatter(self, dir_: Path) -> SkillMeta | None:
        md_path = dir_ / "SKILL.md"
        if not md_path.is_file():
            return None
        try:
            content = md_path.read_text(encoding="utf-8")
        except Exception:
            logger.warning("SKILL.md 读取失败: %s", md_path, exc_info=True)
            return None
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
        sections = self._parse_sections(instructions)
        keywords = self._enrich_keywords(keywords, sections)

        return SkillMeta(
            name=name, description=description, instructions=instructions,
            keywords=keywords, scripts=scripts, root_dir=str(dir_),
            sections=sections,
        )

    def _fallback_minimal(self, dir_: Path) -> SkillMeta:
        name = dir_.name
        description = ""
        instructions = ""
        readme = dir_ / "README.md"
        try:
            if readme.is_file():
                instructions = readme.read_text(encoding="utf-8")
            else:
                md_files = list(dir_.glob("*.md"))
                if md_files:
                    instructions = md_files[0].read_text(encoding="utf-8")
        except Exception:
            logger.warning("兜底解析读取失败: %s", dir_, exc_info=True)

        scripts = self._scan_scripts(dir_)
        sections = self._parse_sections(instructions)
        keywords = self._enrich_keywords([], sections)

        return SkillMeta(
            name=name, description=description, instructions=instructions,
            keywords=keywords, scripts=scripts, root_dir=str(dir_),
            sections=sections,
        )

    @staticmethod
    def _enrich_keywords(keywords: list[str], sections: dict[str, str]) -> list[str]:
        """从章节标题自动提取中文二元组作为关键词兜底。"""
        if keywords:
            return keywords
        if not sections:
            return keywords
        import re
        auto = set()
        for header in sections:
            if header.startswith("_"):
                continue
            cn = "".join(re.findall(r"[一-鿿]+", header))
            for i in range(len(cn) - 1):
                auto.add(cn[i:i + 2])
        return sorted(a for a in auto if len(a) >= 2)[:30]

    def _scan_scripts(self, dir_: Path) -> list[str]:
        scripts_dir = dir_ / "scripts"
        if not scripts_dir.is_dir():
            return []
        return [
            str(p.relative_to(dir_))
            for p in sorted(scripts_dir.rglob("*.py"))
        ]

    @staticmethod
    def _parse_sections(content: str) -> dict[str, str]:
        """按 ## 标题分割 markdown，返回 {标题: 内容} 字典。"""
        sections: dict[str, str] = {}
        parts = content.split("\n## ")
        if not parts:
            return sections
        first = parts[0]
        # 第一部分可能以 ##  开头（内容从行首就是标题），也可能是不含标题的前言
        if first.startswith("## "):
            lines = first[3:].split("\n", 1)
            header = lines[0].strip()
            if header:
                sections[header] = lines[1].strip() if len(lines) > 1 else ""
        elif first.strip():
            sections["_preface"] = first.strip()
        for i, part in enumerate(parts[1:], 1):
            lines = part.split("\n", 1)
            header = lines[0].strip()
            body = lines[1].strip() if len(lines) > 1 else ""
            if not header:
                continue
            if header in sections:
                header = f"{header} ({i})"
            sections[header] = body
        return sections
