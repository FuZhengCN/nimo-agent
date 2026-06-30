"""profile_set 工具：用户通过自然语言指令显式写入个人信息。"""
import logging
from nimo.memory.profile import UserProfile
from nimo.tools.registry import register_tool, ToolResult

logger = logging.getLogger(__name__)

_profile: UserProfile | None = None


def _get_profile() -> UserProfile | None:
    return _profile


def _set_profile(p: UserProfile | None) -> None:
    global _profile
    _profile = p


@register_tool(
    name="profile_set",
    description="记录或更新用户个人信息。用户说'记一下...'或'记住...'时使用。键相同则覆盖旧值，值为空则删除该键。",
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
    try:
        _profile.update({key: value})
        _profile.save()
        logger.info("用户档案已更新：%s = %s", key, value if value else "(已删除)")
        return ToolResult(success=True, data={"key": key, "value": value})
    except Exception as e:
        return ToolResult(success=False, error=str(e))
