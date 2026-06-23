# Nimo Skill 系统设计

## 概述

Skill 是**可插拔的领域能力包**——从 GitHub clone 后即插即用。一个 Skill 是一个包含元数据、行为指令、可执行脚本和知识库的自包含目录。Skill 不是 Tool 的替代，是另一个维度：**Tool 是"手"，Skill 是"方法论"**。

目标：`nimo skill install <github-url>` → 对话中自动可用。

## 核心设计决策

### 决策 1：Skill 格式不强制，三级降级解析

外部 Skill 格式不统一（WorkBuddy 用 `skill.yml`、Claude Code 用 `SKILL.md` frontmatter、社区可能只有 `README.md`），Nimo 不要求单一格式，按优先级尝试解析：

```
discover 一个 Skill 目录：
  ① 有 skill.yml？→ 解析 name/description/keywords/scripts/instructions_file
  ② 有 SKILL.md（YAML frontmatter）？→ 解析 frontmatter，清单和指令合在同一文件
  ③ 以上都没有？→ 目录名当 name，README.md 正文当指令（兜底）
```

永不失败——最差情况也能以最小模式加载。

### 决策 2：激活机制——LLM 主动调用工具，一轮延迟

```
Round N:   LLM 判断需要某 Skill → 调 activate_skill("zhengxi-views")
           返回：技能摘要 + 可用脚本列表（<200 字）

Round N+1: Agent 将完整 SKILL.md 注入 system prompt
           LLM 按 Skill 指令行事 → 调 skill_run(...)
```

为何不把完整 SKILL.md 直接当 tool result 返回？因为会导致双份 token——tool result 留存消息历史，system prompt 也注入一份，浪费上下文。摘要立即可用，完整指令下一轮注入，token 效率最优。

### 决策 3：脚本执行隔离但可访问 Skill 目录

- cwd 设为 Skill 根目录（脚本内 `../references/` 等相对路径正常工作）
- 仅允许执行 skill.yml 中显式声明的 scripts，或自动扫描到的 scripts/ 目录下文件
- 路径遍历防护：拒绝含 `..` 的 script 参数
- 120s 超时（复用现有工具执行超时）

### 决策 4：渐进式披露三层

| 层 | 内容 | 注入时机 | 大小 |
|----|------|---------|------|
| L1 | 所有已安装 Skill 的 name + 一句话描述 | 始终在 system prompt | ~100 字/Skill |
| L2 | 已激活 Skill 的完整 SKILL.md | 激活后的每轮 system prompt | 全量 |
| L3 | 脚本输出 | skill_run 的 tool result | 按需 |

全量常驻在 10+ Skill 时会撑爆上下文窗口，渐进式披露是必需设计。

### 决策 5：与现有工具系统零耦合

```
现有链路（不动）:
  LLM → tapd_query/svn_op → ExecutionEngine → tapd.exe/svn.exe

新增链路:
  LLM → activate_skill/deactivate_skill/skill_run → SkillRegistry → python 脚本

两条链路互不感知，并行共存
```

## 架构

```
~/.nimo/skills/                       nimo/
├── zhengxi-views/        install     ├── skill/
│   ├── skill.yml         ◄────────── │   ├── registry.py    SkillRegistry 单例
│   ├── SKILL.md                      │   ├── installer.py   git clone + pip
│   ├── scripts/                      │   └── __init__.py
│   └── references/                   │
└── another-skill/                    ├── tools/
                                      │   ├── skill_tools.py  activate/deactivate/run
                                      │   └── ...（tapd/svn 不动）
                                      │
                                      ├── agent.py   init SkillRegistry + 注入 system prompt
                                      └── main.py    skill install/list/uninstall
```

## 数据流

```
启动 → SkillRegistry.discover(~/.nimo/skills/)
     → 提取各 skill.yml 元数据
     → L1 元数据追加到 system prompt

对话 → LLM 判断需要某 Skill → 调 activate_skill("name")
     → SkillRegistry 加载 SKILL.md，返回摘要
     → 下轮起完整指令注入 system prompt（L2）

     → LLM 按 SKILL.md 指示 → 调 skill_run("name", "script.py", ["args"])
     → cwd=Skill根目录，执行脚本，返回输出（L3）
```

## 关键接口

### SkillRegistry

```python
class SkillRegistry:
    _instance: "SkillRegistry | None"    # 单例

    def discover(self, skills_dir: str) -> int
    def list_meta(self) -> list[dict]    # L1: [{"name":..., "description":..., "keywords":[...]}]
    def activate(self, name: str) -> str # 返回摘要
    def deactivate(self) -> None
    def get_active_instructions(self) -> str | None  # 供 Agent 注入
    async def run_script(self, name: str, script: str, args: list[str]) -> ToolResult

    # 内部降级链
    def _try_skill_yml(self, dir_) -> SkillMeta | None
    def _try_skill_md_frontmatter(self, dir_) -> SkillMeta | None
    def _fallback_minimal(self, dir_) -> SkillMeta
```

### SkillMeta

```python
@dataclass
class SkillMeta:
    name: str           # skill.yml → SKILL.md frontmatter → 目录名
    description: str    # 同上降级
    instructions: str   # SKILL.md（或备选）完整正文
    keywords: list[str] # 显式声明 或 从 description 分词提取
    scripts: list[str]  # 显式声明 或 自动扫描 scripts/ 目录
    root_dir: str       # Skill 根目录
```

### 工具（LLM 可见）

```python
# nimo/tools/skill_tools.py
@register_tool("activate_skill", "激活指定技能以获取领域知识和操作指南", {...})
async def activate_skill(name: str) -> ToolResult

@register_tool("deactivate_skill", "清空当前激活的技能", {...})
async def deactivate_skill() -> ToolResult

@register_tool("skill_run", "执行已激活技能的脚本", {...})
async def skill_run(skill: str, script: str, args: list[str]) -> ToolResult
```

### 内置命令

```
skill install <github-url>     → git clone 到 ~/.nimo/skills/，检测 requirements.txt
skill list                     → 展示已安装 Skill 及其状态
skill uninstall <name>         → 删除 Skill 目录
```

## Agent 核心循环改动

```python
# agent.py run()，每轮 LLM 调用前：
system_prompt = self._system_prompt               # 基础 prompt（含 L1 元数据列表）
instructions = self._skill_registry.get_active_instructions()
if instructions:
    system_prompt = system_prompt + "\n\n## 已激活技能\n" + instructions
```

改动量为 3 行：获取激活指令 + 拼接。其余逻辑不变。

## 安全边界

- **脚本白名单**：仅允许执行 skill.yml 声明或自动扫描到的 scripts/ 下脚本
- **路径遍历防护**：`skill_run` 的 `script` 参数拒绝含 `..` 的值
- **cwd 隔离**：脚本执行 cwd 限制在 Skill 根目录，不访问 Nimo 项目文件
- **超时**：120s，复用现有工具执行超时机制
- **依赖提示**：`skill install` 时检测 `requirements.txt`，提示用户 pip install，不自动执行

## 改动清单

| # | 文件 | 操作 | 说明 |
|---|------|------|------|
| 1 | `nimo/skill/__init__.py` | 新建 | 导出 SkillRegistry、SkillMeta、Installer |
| 2 | `nimo/skill/registry.py` | 新建 | 三级降级解析 + 激活/停用/脚本执行 |
| 3 | `nimo/skill/installer.py` | 新建 | clone + requirements 检测 + list + uninstall |
| 4 | `nimo/tools/skill_tools.py` | 新建 | activate_skill / deactivate_skill / skill_run |
| 5 | `nimo/agent.py` | 修改 | init SkillRegistry + discover + 每轮注入激活指令 |
| 6 | `nimo/main.py` | 修改 | build_agent 初始化 + skill install/list/uninstall 命令 |
| 7 | `tests/test_skill.py` | 新建 | discover 三路径 / activate / deactivate / run_script / install |

**现有 TAPD/SVN 工具链路：零改动。**

## 不变项

- `ToolRegistry` 及其自动发现机制不变
- `ExecutionEngine` 不变
- `prompts/system.md` 不变
- `tapd_query`、`tapd_cli`、`svn_op`、`svn` 工具定义和参数格式不变
- 所有现有测试不变
