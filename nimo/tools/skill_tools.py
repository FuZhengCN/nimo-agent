"""Skill 工具：activate_skill / deactivate_skill / skill_run。"""
from nimo.tools.registry import register_tool, ToolResult


def _get_skill_registry():
    """延迟导入 SkillRegistry，避免循环导入（skill_tools → skill.registry → tools.registry → tools.__init__ → skill_tools）。"""
    from nimo.skill.registry import SkillRegistry
    return SkillRegistry.get_instance()


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
    registry = _get_skill_registry()
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
    registry = _get_skill_registry()
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
        "required": ["skill", "script"],
    },
)
async def skill_run(skill: str, script: str, args: list[str] | None = None) -> ToolResult:
    registry = _get_skill_registry()
    # 自动激活：LLM 经常跳过 activate_skill 直接调 skill_run，
    # 此处静默激活，确保下一轮 system prompt 中注入技能指令。
    try:
        registry.activate(skill)
    except ValueError:
        pass
    return await registry.run_script(skill, script, args or [])
