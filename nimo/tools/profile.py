"""profile_set 工具：用户通过自然语言指令显式写入个人信息。"""
from nimo.memory.profile import UserProfile
from nimo.tools.registry import register_tool, ToolResult

_profile: UserProfile | None = None


def _set_profile(p: UserProfile | None) -> None:
    global _profile
    _profile = p


@register_tool(
    name="profile_set",
    description="记录或更新用户个人信息。用户说'记一下...'或'记住...'时使用。键相同则覆盖旧值。",
    parameters={
        "type": "object",
        "properties": {
            "key": {"type": "string", "description": "事实类别，如 姓名、工号、团队成员、常用项目"},
            "value": {"type": "string", "description": "具体内容，如 张三、755、张三/李四"},
        },
        "required": ["key", "value"],
    },
)
async def profile_set(key: str, value: str) -> ToolResult:
    if _profile is None:
        return ToolResult(success=False, error="用户档案未初始化")
    if not value:
        return ToolResult(success=False, error="值不能为空，如需删除请直接编辑 ~/.nimo/profile.json")
    _profile.update({key: value})
    _profile.save()
    return ToolResult(success=True, data={"key": key, "value": value})
