# Nimo Skill 系统实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现可插拔的外部 Skill 系统——`nimo skill install <github-url>` 即插即用，三级格式降级解析，渐进式披露（L1 元数据 → L2 指令注入 → L3 脚本执行）。

**Architecture:** 新增 `nimo/skill/` 包（SkillRegistry 单例 + Installer），新增 `nimo/tools/skill_tools.py`（三个 LLM 可见工具），修改 `agent.py`（system prompt 注入）和 `main.py`（内置命令）。现有 TAPD/SVN 工具链路零改动。

**Tech Stack:** Python 3.10+, PyYAML, asyncio subprocess, git CLI

---

### Task 1: 创建 nimo/skill 包骨架 + SkillMeta 数据类

**Files:**
- Create: `nimo/skill/__init__.py`
- Create: `nimo/skill/registry.py`（骨架）

- [ ] **Step 1: 创建 `nimo/skill/__init__.py`**

```python
from nimo.skill.registry import SkillRegistry, SkillMeta
from nimo.skill.installer import Installer

__all__ = ["SkillRegistry", "SkillMeta", "Installer"]
```

- [ ] **Step 2: 创建 `nimo/skill/registry.py`——SkillMeta + SkillRegistry 骨架**

```python
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
```

- [ ] **Step 3: 确认文件存在且可导入**

```bash
python -c "from nimo.skill import SkillRegistry, SkillMeta, Installer; print('import OK')"
```

Expected: `import OK`（Installer 导入会因为文件不存在报错，先忽略）

- [ ] **Step 4: 提交**

```bash
git add nimo/skill/__init__.py nimo/skill/registry.py
git commit -m "feat: SkillMeta 数据类 + SkillRegistry 骨架——单例、list_meta、get_active_instructions"
```

---

### Task 2: SkillRegistry.discover()——三级降级解析

**Files:**
- Modify: `nimo/skill/registry.py`

- [ ] **Step 1: 添加 discover() 方法**

在 `SkillRegistry` 类中添加：

```python
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
```

- [ ] **Step 2: 添加 _try_skill_yml() 方法**

```python
    def _try_skill_yml(self, dir_: Path) -> SkillMeta | None:
        yml_path = dir_ / "skill.yml"
        if not yml_path.is_file():
            return None
        try:
            import yaml
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
```

- [ ] **Step 3: 添加 _try_skill_md_frontmatter() 方法**

```python
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
            import yaml
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
```

- [ ] **Step 4: 添加 _fallback_minimal() + _scan_scripts() 方法**

```python
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
```

- [ ] **Step 5: 验证——用临时目录测试三级降级**

```bash
python -c "
import tempfile, os
from pathlib import Path
from nimo.skill.registry import SkillRegistry

SkillRegistry.reset()
reg = SkillRegistry.get_instance()

with tempfile.TemporaryDirectory() as d:
    # ① skill.yml 格式
    s1 = Path(d) / 'skill-a'
    s1.mkdir()
    (s1 / 'skill.yml').write_text('name: ska\ndescription: desc-a\nkeywords: [kw1, kw2]', encoding='utf-8')
    (s1 / 'SKILL.md').write_text('# Hello', encoding='utf-8')

    # ② SKILL.md frontmatter 格式
    s2 = Path(d) / 'skill-b'
    s2.mkdir()
    (s2 / 'SKILL.md').write_text('---\nname: skb\ndescription: desc-b\n---\n# Body', encoding='utf-8')

    # ③ 仅 README.md 兜底
    s3 = Path(d) / 'skill-c'
    s3.mkdir()
    (s3 / 'README.md').write_text('# About skill-c', encoding='utf-8')

    n = reg.discover(d)
    print(f'Discovered: {n}')
    for m in reg.list_meta():
        print(f'  {m[\"name\"]}: {m[\"description\"][:50]}')
"
```

Expected:
```
Discovered: 3
  ska: desc-a
  skb: desc-b
  skill-c:
```

- [ ] **Step 6: 提交**

```bash
git add nimo/skill/registry.py
git commit -m "feat: SkillRegistry.discover——三级降级解析（skill.yml / SKILL.md frontmatter / README兜底）"
```

---

### Task 3: SkillRegistry activate / deactivate / run_script

**Files:**
- Modify: `nimo/skill/registry.py`

- [ ] **Step 1: 添加 activate() 和 deactivate() 方法**

```python
    def activate(self, name: str) -> str:
        meta = self._skills.get(name)
        if meta is None:
            raise ValueError(f"未找到技能：{name}，可用：{', '.join(self._skills.keys())}")
        self._active_instructions = meta.instructions
        script_list = ", ".join(meta.scripts) if meta.scripts else "无"
        return f"已激活技能「{meta.name}」：{meta.description[:120]}。可用脚本：{script_list}"

    def deactivate(self) -> None:
        self._active_instructions = None
```

- [ ] **Step 2: 添加 run_script() 方法**

```python
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
```

- [ ] **Step 3: 验证——激活和脚本执行**

```bash
python -c "
import asyncio, tempfile
from pathlib import Path
from nimo.skill.registry import SkillRegistry

SkillRegistry.reset()
reg = SkillRegistry.get_instance()

with tempfile.TemporaryDirectory() as d:
    s = Path(d) / 'test-skill'
    s.mkdir()
    scripts = s / 'scripts'
    scripts.mkdir(parents=True)
    (s / 'skill.yml').write_text('name: test-skill\ndescription: 测试技能\nscripts:\n  - scripts/hello.py', encoding='utf-8')
    (scripts / 'hello.py').write_text('import sys; print(\"Hello\", *sys.argv[1:])', encoding='utf-8')
    reg.discover(d)

    # activate
    summary = reg.activate('test-skill')
    print(f'activate: {summary}')
    print(f'instructions: {bool(reg.get_active_instructions())}')

    # run_script
    result = asyncio.run(reg.run_script('test-skill', 'scripts/hello.py', ['world']))
    print(f'run_script: success={result.success}, data={result.data}')

    # deactivate
    reg.deactivate()
    print(f'deactivated: {reg.get_active_instructions() is None}')
"
```

Expected:
```
activate: 已激活技能「test-skill」：测试技能。可用脚本：scripts/hello.py
instructions: True
run_script: success=True, data=Hello world
deactivated: True
```

- [ ] **Step 4: 提交**

```bash
git add nimo/skill/registry.py
git commit -m "feat: SkillRegistry activate/deactivate/run_script——激活注入指令，脚本白名单+路径防护+120s超时"
```

---

### Task 4: Installer——git clone + pip 提示

**Files:**
- Create: `nimo/skill/installer.py`

- [ ] **Step 1: 创建 `nimo/skill/installer.py`**

```python
"""技能安装器：git clone、卸载、列表。"""
import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


class Installer:
    def __init__(self, skills_dir: str):
        self._skills_dir = Path(skills_dir)

    def install(self, url: str) -> str:
        self._skills_dir.mkdir(parents=True, exist_ok=True)
        name = url.rstrip("/").split("/")[-1]
        if name.endswith(".git"):
            name = name[:-4]
        target = self._skills_dir / name
        if target.exists():
            return f"技能目录已存在：{target}\n如需重装请先 skill uninstall {name}"

        result = subprocess.run(
            ["git", "clone", url, str(target)],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            return f"git clone 失败：{result.stderr.strip() or result.stdout.strip()}"

        req_path = target / "requirements.txt"
        if req_path.is_file():
            return (
                f"已安装 {name} 到 {target}\n"
                f"检测到 requirements.txt，请手动运行：pip install -r {req_path}"
            )
        return f"已安装 {name} 到 {target}"

    def uninstall(self, name: str) -> str:
        target = self._skills_dir / name
        if not target.exists():
            return f"技能目录不存在：{target}"
        shutil.rmtree(target)
        return f"已卸载 {name}"

    def list_installed(self) -> list[tuple[str, str]]:
        if not self._skills_dir.is_dir():
            return []
        result = []
        for entry in sorted(self._skills_dir.iterdir()):
            if entry.is_dir():
                result.append((entry.name, str(entry)))
        return result
```

- [ ] **Step 2: 验证——install 需要网络，先验证 list 和 uninstall 逻辑**

```bash
python -c "
import tempfile, os
from pathlib import Path
from nimo.skill.installer import Installer

with tempfile.TemporaryDirectory() as d:
    inst = Installer(d)
    # 空目录 list
    assert inst.list_installed() == [], 'empty list should be []'

    # 手动造一个假技能目录模拟已安装
    (Path(d) / 'fake-skill').mkdir()
    skills = inst.list_installed()
    assert len(skills) == 1 and skills[0][0] == 'fake-skill', f'unexpected: {skills}'

    # uninstall
    msg = inst.uninstall('fake-skill')
    assert '已卸载' in msg, f'unexpected: {msg}'
    assert inst.list_installed() == [], 'should be empty after uninstall'

    # uninstall 不存在的
    msg = inst.uninstall('nonexistent')
    assert '不存在' in msg, f'unexpected: {msg}'

    print('installer tests passed')
"
```

Expected: `installer tests passed`

- [ ] **Step 3: 提交**

```bash
git add nimo/skill/installer.py
git commit -m "feat: Installer——git clone 安装 + requirements 检测 + uninstall + list"
```

---

### Task 5: skill_tools.py——LLM 可见的三个工具

**Files:**
- Create: `nimo/tools/skill_tools.py`

- [ ] **Step 1: 创建 `nimo/tools/skill_tools.py`**

```python
"""Skill 工具：activate_skill / deactivate_skill / skill_run。"""
import logging

from nimo.skill.registry import SkillRegistry
from nimo.tools.registry import register_tool, ToolResult

logger = logging.getLogger(__name__)


@register_tool(
    name="activate_skill",
    description="激活指定技能以获取领域知识和操作指南。激活后下一轮对话起技能指令将生效。"
                "当前轮仅返回技能摘要（含可用脚本列表）。",
    parameters={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "技能名称（见 system prompt 中可用技能列表）",
            },
        },
        "required": ["name"],
    },
)
async def activate_skill(name: str) -> ToolResult:
    registry = SkillRegistry.get_instance()
    try:
        summary = registry.activate(name)
    except ValueError as e:
        return ToolResult(success=False, error=str(e))
    return ToolResult(success=True, data=summary)


@register_tool(
    name="deactivate_skill",
    description="清空当前激活的技能，后续对话不再受其指令约束。",
    parameters={"type": "object", "properties": {}, "required": []},
)
async def deactivate_skill() -> ToolResult:
    registry = SkillRegistry.get_instance()
    registry.deactivate()
    return ToolResult(success=True, data="已清空激活的技能")


@register_tool(
    name="skill_run",
    description="执行已安装技能的脚本。仅可执行该技能声明的脚本（白名单），"
                "脚本在技能根目录下运行以正确访问 references/ 等资源。",
    parameters={
        "type": "object",
        "properties": {
            "skill": {"type": "string", "description": "技能名称"},
            "script": {
                "type": "string",
                "description": "脚本相对路径（如 scripts/search.py）",
            },
            "args": {
                "type": "array",
                "items": {"type": "string"},
                "description": "脚本命令行参数",
            },
        },
        "required": ["skill", "script", "args"],
    },
)
async def skill_run(skill: str, script: str, args: list[str]) -> ToolResult:
    registry = SkillRegistry.get_instance()
    return await registry.run_script(skill, script, args)
```

- [ ] **Step 2: 验证工具已自动注册**

```bash
python -c "
import nimo.tools  # 触发工具自动发现（含 skill_tools）
from nimo.tools.registry import ToolRegistry

reg = ToolRegistry.get_instance()
tool_names = [t[0] for t in reg.list_tools()]
print('Tools:', tool_names)
assert 'activate_skill' in tool_names, 'activate_skill missing'
assert 'deactivate_skill' in tool_names, 'deactivate_skill missing'
assert 'skill_run' in tool_names, 'skill_run missing'
print('All 3 skill tools registered')
"
```

Expected: `All 3 skill tools registered`

- [ ] **Step 3: 提交**

```bash
git add nimo/tools/skill_tools.py
git commit -m "feat: skill_tools——activate_skill / deactivate_skill / skill_run 三个 LLM 可见工具"
```

---

### Task 6: Agent 集成——discover + system prompt 注入

**Files:**
- Modify: `nimo/agent.py:19-39`（`__init__`）
- Modify: `nimo/agent.py:65-82`（`_load_system_prompt`）
- Modify: `nimo/agent.py:151-169`（`run()` 循环中的 LLM 调用）
- Modify: `nimo/agent.py:254-269`（`run()` 结尾兜底 LLM 调用）

- [ ] **Step 1: 在 `agent.py` 顶部添加 import**

在现有 `from pathlib import Path` 之后添加：

```python
from nimo.skill.registry import SkillRegistry
```

- [ ] **Step 2: 修改 `__init__`——在加载 system prompt 之前初始化 SkillRegistry**

`agent.py:35-40`，当前为：
```python
class Agent:
    def __init__(self, config: Config):
        self._config = config
        self._llm_client = LLMClient(config)
        self._registry = ToolRegistry.get_instance()
        self._system_prompt = self._load_system_prompt()
```

修改为：
```python
class Agent:
    def __init__(self, config: Config):
        self._config = config
        self._llm_client = LLMClient(config)
        self._registry = ToolRegistry.get_instance()
        self._skill_registry = SkillRegistry.get_instance()
        skills_dir = str(Path.home() / ".nimo" / "skills")
        self._skill_registry.discover(skills_dir)
        self._system_prompt = self._load_system_prompt()
```

- [ ] **Step 3: 修改 `_load_system_prompt()`——末尾追加 L1 技能元数据**

`agent.py:77-82`，当前为：
```python
        if tool_lines:
            base += "\n\n## 可用工具\n" + "\n".join(tool_lines)
        return base
```

修改为：
```python
        if tool_lines:
            base += "\n\n## 可用工具\n" + "\n".join(tool_lines)
        skill_meta = self._skill_registry.list_meta()
        if skill_meta:
            lines = ["\n## 可用技能\n"]
            for m in skill_meta:
                desc = m["description"][:100] if m["description"] else "无描述"
                lines.append(f"- `{m['name']}`：{desc}")
            base += "\n".join(lines)
        return base
```

- [ ] **Step 4: 修改 `run()` 循环——每轮 LLM 调用前注入激活的 Skill 指令**

`agent.py:159-163`，当前为：
```python
            try:
                response = await self._llm_client.chat(
                    messages=messages,
                    tools=self._tool_definitions,
                    system_prompt=self._system_prompt,
                )
```

修改为：
```python
            system_prompt = self._system_prompt
            instructions = self._skill_registry.get_active_instructions()
            if instructions:
                system_prompt = system_prompt + "\n\n## 已激活技能\n" + instructions
            try:
                response = await self._llm_client.chat(
                    messages=messages,
                    tools=self._tool_definitions,
                    system_prompt=system_prompt,
                )
```

- [ ] **Step 5: 同样修改 `run()` 结尾兜底 LLM 调用**

`agent.py:254-261`，当前为：
```python
            response = await self._llm_client.chat(
                messages=messages,
                tools=[],
                system_prompt=self._system_prompt,
            )
```

修改为：
```python
            system_prompt = self._system_prompt
            instructions = self._skill_registry.get_active_instructions()
            if instructions:
                system_prompt = system_prompt + "\n\n## 已激活技能\n" + instructions
            response = await self._llm_client.chat(
                messages=messages,
                tools=[],
                system_prompt=system_prompt,
            )
```

- [ ] **Step 6: 验证——检查导入和基本结构**

```bash
python -c "
from nimo.config import Config, LLMConfig, TapdConfig
from nimo.agent import Agent

config = Config(
    llm=LLMConfig(api_key='sk-test', base_url='https://api.deepseek.com',
                  model='deepseek-chat', max_tool_rounds=5, history_rounds=10),
    tapd=TapdConfig(api_base='https://api.tapd.cn', access_token='tok'),
)
agent = Agent(config)
print('Skill registry:', type(agent._skill_registry).__name__)
print('System prompt ends with skills?', '## 可用技能' in agent._system_prompt or 'no skills installed (expected)')
"
```

Expected: `Skill registry: SkillRegistry` + 无技能时不会崩溃

- [ ] **Step 7: 提交**

```bash
git add nimo/agent.py
git commit -m "feat: Agent 集成 SkillRegistry——启动时 discover，每轮 system prompt 注入已激活技能指令"
```

---

### Task 7: main.py 集成——skill install/list/uninstall 命令

**Files:**
- Modify: `nimo/main.py`

- [ ] **Step 1: 在 `main.py` 顶部添加 import**

在现有 `from nimo.config import Config, load_config` 之后添加：

```python
from pathlib import Path
from nimo.skill.registry import SkillRegistry
from nimo.skill.installer import Installer
```

- [ ] **Step 2: 在 `main()` 函数中定义 skills_dir，在 `/help` 之前添加 skill 命令处理**

`main.py:271-291`，在 `/help` 块之前插入 skill 命令块：

```python
        skills_dir = str(Path.home() / ".nimo" / "skills")
        if user_input.strip().startswith("skill "):
            parts = user_input.strip().split(maxsplit=2)
            if len(parts) < 2:
                print("用法：skill install <url> | skill list | skill uninstall <name>")
                continue
            cmd = parts[1]
            if cmd == "install" and len(parts) >= 3:
                url = parts[2]
                installer = Installer(skills_dir)
                result = installer.install(url)
                print(result)
                if "已安装" in result:
                    SkillRegistry.get_instance().discover(skills_dir)
                    agent._system_prompt = agent._load_system_prompt()
                continue
            elif cmd == "list":
                installer = Installer(skills_dir)
                skills = installer.list_installed()
                if skills:
                    for name, path in skills:
                        print(f"  {name}  ({path})")
                else:
                    print("暂无已安装的技能。\n安装：skill install <github-url>")
                continue
            elif cmd == "uninstall" and len(parts) >= 3:
                name = parts[2]
                installer = Installer(skills_dir)
                result = installer.uninstall(name)
                print(result)
                SkillRegistry.get_instance().discover(skills_dir)
                agent._system_prompt = agent._load_system_prompt()
                continue
            else:
                print("用法：skill install <url> | skill list | skill uninstall <name>")
                continue
```

插入位置：在 `/chain` 处理块之后，`/help` 处理块之前。

- [ ] **Step 3: 同时在 `/help` 输出中追加 skill 命令帮助**

`main.py:288`，"所有操作通过自然语言驱动" 之前，添加：

```python
          · skill install <url>  从 GitHub 安装技能
          · skill list           查看已安装技能
          · skill uninstall <名> 卸载技能
```

- [ ] **Step 4: 验证——检查导入不报错**

```bash
python -c "
from pathlib import Path
from nimo.skill.registry import SkillRegistry
from nimo.skill.installer import Installer
print('All imports OK')
"
```

Expected: `All imports OK`

- [ ] **Step 5: 提交**

```bash
git add nimo/main.py
git commit -m "feat: main.py 新增 skill install/list/uninstall 内置命令"
```

---

### Task 8: 测试套件

**Files:**
- Create: `tests/test_skill.py`

- [ ] **Step 1: 创建 `tests/test_skill.py`**

```python
"""Skill 系统测试——discover / activate / deactivate / run_script / installer。"""
import asyncio
import tempfile
from pathlib import Path

import pytest

from nimo.skill.registry import SkillRegistry
from nimo.skill.installer import Installer


@pytest.fixture(autouse=True)
def reset_registry():
    SkillRegistry.reset()


# ---------------------------------------------------------------------------
# discover 三级降级
# ---------------------------------------------------------------------------

def _make_skill_yml(tmpdir: str, name: str, desc: str = "测试技能",
                     with_instructions: bool = True, with_scripts: bool = False):
    """Helper：创建 skill.yml 格式的技能目录。"""
    skill_dir = Path(tmpdir) / name
    skill_dir.mkdir()
    yml = f"name: {name}\ndescription: {desc}\nkeywords: [kw1, kw2]\n"
    if with_scripts:
        scripts_dir = skill_dir / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "hello.py").write_text("print('hello')")
        yml += "scripts:\n  - scripts/hello.py\n"
    (skill_dir / "skill.yml").write_text(yml, encoding="utf-8")
    if with_instructions:
        (skill_dir / "SKILL.md").write_text(f"# {name} instructions", encoding="utf-8")
    return skill_dir


def _make_skill_md_frontmatter(tmpdir: str, name: str, desc: str = "测试技能"):
    """Helper：创建 SKILL.md frontmatter 格式的技能目录。"""
    skill_dir = Path(tmpdir) / name
    skill_dir.mkdir()
    md = f"---\nname: {name}\ndescription: {desc}\nkeywords: [kw]\n---\n\n# {name} body"
    (skill_dir / "SKILL.md").write_text(md, encoding="utf-8")
    return skill_dir


def _make_skill_fallback(tmpdir: str, name: str):
    """Helper：创建仅 README.md 的兜底格式。"""
    skill_dir = Path(tmpdir) / name
    skill_dir.mkdir()
    (skill_dir / "README.md").write_text(f"# {name} readme", encoding="utf-8")
    return skill_dir


def test_discover_skill_yml():
    reg = SkillRegistry.get_instance()
    with tempfile.TemporaryDirectory() as d:
        _make_skill_yml(d, "ska", desc="技能A")
        n = reg.discover(d)
        assert n == 1
        meta = reg.list_meta()
        assert meta[0]["name"] == "ska"
        assert "技能A" in meta[0]["description"]


def test_discover_skill_md_frontmatter():
    reg = SkillRegistry.get_instance()
    with tempfile.TemporaryDirectory() as d:
        _make_skill_md_frontmatter(d, "skb", desc="技能B")
        n = reg.discover(d)
        assert n == 1
        meta = reg.list_meta()
        assert meta[0]["name"] == "skb"
        assert "技能B" in meta[0]["description"]


def test_discover_fallback_minimal():
    reg = SkillRegistry.get_instance()
    with tempfile.TemporaryDirectory() as d:
        _make_skill_fallback(d, "skc")
        n = reg.discover(d)
        assert n == 1
        meta = reg.list_meta()
        assert meta[0]["name"] == "skc"


def test_discover_mixed_formats():
    reg = SkillRegistry.get_instance()
    with tempfile.TemporaryDirectory() as d:
        _make_skill_yml(d, "ska")
        _make_skill_md_frontmatter(d, "skb")
        _make_skill_fallback(d, "skc")
        n = reg.discover(d)
        assert n == 3


def test_discover_empty_directory():
    reg = SkillRegistry.get_instance()
    with tempfile.TemporaryDirectory() as d:
        n = reg.discover(d)
        assert n == 0
        assert reg.list_meta() == []


def test_discover_no_directory():
    reg = SkillRegistry.get_instance()
    n = reg.discover("/tmp/__nimo_nonexistent_skills_dir__")
    assert n == 0


# ---------------------------------------------------------------------------
# activate / deactivate
# ---------------------------------------------------------------------------

def test_activate_and_deactivate():
    reg = SkillRegistry.get_instance()
    with tempfile.TemporaryDirectory() as d:
        _make_skill_yml(d, "ska", desc="技能A", with_instructions=True)
        reg.discover(d)

        summary = reg.activate("ska")
        assert "已激活" in summary
        assert "技能A" in summary
        assert reg.get_active_instructions() is not None

        reg.deactivate()
        assert reg.get_active_instructions() is None


def test_activate_nonexistent():
    reg = SkillRegistry.get_instance()
    with pytest.raises(ValueError, match="未找到技能"):
        reg.activate("nonexistent")


def test_deactivate_when_none_active():
    reg = SkillRegistry.get_instance()
    reg.deactivate()  # 不抛异常
    assert reg.get_active_instructions() is None


# ---------------------------------------------------------------------------
# run_script
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_script_success():
    reg = SkillRegistry.get_instance()
    with tempfile.TemporaryDirectory() as d:
        _make_skill_yml(d, "ska", with_scripts=True)
        reg.discover(d)

        result = await reg.run_script("ska", "scripts/hello.py", [])
        assert result.success is True
        assert result.data == "hello"


@pytest.mark.asyncio
async def test_run_script_not_in_whitelist():
    reg = SkillRegistry.get_instance()
    with tempfile.TemporaryDirectory() as d:
        _make_skill_yml(d, "ska")
        reg.discover(d)

        result = await reg.run_script("ska", "scripts/nonexistent.py", [])
        assert result.success is False
        assert "白名单" in result.error or "不在" in result.error


@pytest.mark.asyncio
async def test_run_script_path_traversal():
    reg = SkillRegistry.get_instance()
    with tempfile.TemporaryDirectory() as d:
        _make_skill_yml(d, "ska")
        reg.discover(d)

        result = await reg.run_script("ska", "../etc/passwd", [])
        assert result.success is False
        assert "路径遍历" in result.error


@pytest.mark.asyncio
async def test_run_script_unknown_skill():
    reg = SkillRegistry.get_instance()
    result = await reg.run_script("nonexistent", "test.py", [])
    assert result.success is False
    assert "未找到技能" in result.error


@pytest.mark.asyncio
async def test_run_script_returns_stderr_on_failure():
    reg = SkillRegistry.get_instance()
    with tempfile.TemporaryDirectory() as d:
        skill_dir = Path(d) / "ska"
        skill_dir.mkdir()
        scripts_dir = skill_dir / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "fail.py").write_text("import sys; sys.exit(1)")
        (skill_dir / "skill.yml").write_text(
            "name: ska\nscripts:\n  - scripts/fail.py", encoding="utf-8"
        )
        reg.discover(d)

        result = await reg.run_script("ska", "scripts/fail.py", [])
        assert result.success is False
        assert "非零退出码" in result.error or result.error


# ---------------------------------------------------------------------------
# Installer
# ---------------------------------------------------------------------------

def test_installer_list_empty():
    with tempfile.TemporaryDirectory() as d:
        inst = Installer(d)
        assert inst.list_installed() == []


def test_installer_list_and_uninstall():
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "my-skill").mkdir()
        inst = Installer(d)
        skills = inst.list_installed()
        assert len(skills) == 1
        assert skills[0][0] == "my-skill"

        msg = inst.uninstall("my-skill")
        assert "已卸载" in msg
        assert inst.list_installed() == []


def test_installer_uninstall_nonexistent():
    with tempfile.TemporaryDirectory() as d:
        inst = Installer(d)
        msg = inst.uninstall("nonexistent")
        assert "不存在" in msg
```

- [ ] **Step 2: 运行测试套件**

```bash
pytest tests/test_skill.py -v
```

Expected: 14 passed

- [ ] **Step 3: 确认全部已有测试仍然通过**

```bash
pytest tests/ -v --timeout=30
```

Expected: 全部通过（无现有测试因 Skill 系统引入而破坏）

- [ ] **Step 4: 提交**

```bash
git add tests/test_skill.py
git commit -m "test: Skill 系统全覆盖——discover三级降级/activate/deactivate/run_script/installer 共14用例"
```

---

## 验证清单

实现完成后按顺序验证：

1. `python -c "from nimo.skill import SkillRegistry, SkillMeta, Installer; print('OK')"` — 包导入正常
2. `pytest tests/test_skill.py -v` — 14 测试通过
3. `pytest tests/ -v` — 全部已有测试无回归
4. `python -m nimo.main` — 启动不报错，system prompt 末尾有 `## 可用技能` 段（无已安装技能时为空）
5. `skill list` — 输出"暂无已安装的技能"
6. `skill install https://github.com/lyra81604/zhengxi-views` — clone 成功，提示 requirements.txt
7. `skill list` — 显示 zhengxi-views
8. `skill uninstall zhengxi-views` — 卸载成功
