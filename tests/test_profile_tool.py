import pytest
from unittest.mock import patch
from nimo.memory.profile import UserProfile
from nimo.tools.registry import ToolRegistry

# 在模块导入时（collection 阶段，任何测试执行之前）保存原始 execute 方法。
# test_agent.py 会在执行阶段将其替换为 AsyncMock，此引用用于在 tearDown 中恢复。
_original_execute = ToolRegistry.get_instance().execute


@pytest.fixture(autouse=True)
def _isolate_registry():
    """隔离 ToolRegistry 免受其他测试的 mock 污染。

    test_agent.py 通过 agent._registry.execute = AsyncMock(...) 替换了单例的
    execute 方法且未恢复。本 fixture 在每次测试前恢复原始 execute，测试后恢复
    测试前的状态（以避免破坏其他测试的"连续 mock"假设）。
    """
    registry = ToolRegistry.get_instance()
    saved = registry.execute
    registry.execute = _original_execute
    yield
    registry.execute = saved


@pytest.fixture(autouse=True)
def _mock_profile_save():
    """禁止 profile.save() 写入真实 ~/.nimo/profile.json。"""
    with patch.object(UserProfile, "save", return_value=None):
        yield


@pytest.mark.asyncio
async def test_profile_set_writes():
    """验证 profile_set 写入。"""
    from nimo.tools.profile import _set_profile

    p = UserProfile()
    _set_profile(p)

    result = await ToolRegistry.get_instance().execute("profile_set", {
        "key": "姓名",
        "value": "张三",
    })

    assert result.success
    assert p.facts == {"姓名": "张三"}


@pytest.mark.asyncio
async def test_profile_set_overwrites():
    """验证同名键覆盖。"""
    from nimo.tools.profile import _set_profile

    p = UserProfile()
    p.update({"姓名": "张三"})
    _set_profile(p)

    result = await ToolRegistry.get_instance().execute("profile_set", {
        "key": "姓名",
        "value": "李四",
    })

    assert result.success
    assert p.facts == {"姓名": "李四"}


@pytest.mark.asyncio
async def test_profile_set_rejects_empty_value():
    """验证空值被拒绝，不删除已有键。"""
    from nimo.tools.profile import _set_profile

    p = UserProfile()
    p.update({"姓名": "张三", "角色": "工程师"})
    _set_profile(p)

    result = await ToolRegistry.get_instance().execute("profile_set", {
        "key": "姓名",
        "value": "",
    })

    assert not result.success
    assert "不能为空" in result.error
    assert "姓名" in p.facts
    assert "角色" in p.facts


@pytest.mark.asyncio
async def test_profile_set_returns_error_when_not_injected():
    """验证 profile 未注入时返回错误。"""
    from nimo.tools.profile import _set_profile

    # 确保没有注入 profile
    _set_profile(None)

    result = await ToolRegistry.get_instance().execute("profile_set", {
        "key": "姓名",
        "value": "张三",
    })

    assert not result.success
    assert "未初始化" in result.error


def test_profile_set_tool_registered():
    """验证 profile_set 已注册到 ToolRegistry。"""
    # 触发模块级 @register_tool
    import nimo.tools.profile  # noqa: F401
    registry = ToolRegistry.get_instance()
    tools = dict(registry.list_tools())
    assert "profile_set" in tools
