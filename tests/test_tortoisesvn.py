import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from nimo.config import Config, LLMConfig, TapdConfig, TortoiseSvnConfig

import nimo.tools.tortoisesvn


@pytest.fixture
def multi_config():
    """两个项目，无默认。"""
    return Config(
        llm=LLMConfig(api_key="sk-test", base_url="https://api.deepseek.com",
                      model="deepseek-chat", max_tool_rounds=5, history_rounds=10),
        tapd=TapdConfig(api_base="https://api.tapd.cn", access_token="token123"),
        tortoisesvn=TortoiseSvnConfig(
            paths={"proj1": r"C:\test\proj1", "proj2": r"D:\other\proj2"},
        ),
    )


@pytest.fixture
def single_config():
    """单项目，自动匹配。"""
    return Config(
        llm=LLMConfig(api_key="sk-test", base_url="https://api.deepseek.com",
                      model="deepseek-chat", max_tool_rounds=5, history_rounds=10),
        tapd=TapdConfig(api_base="https://api.tapd.cn", access_token="token123"),
        tortoisesvn=TortoiseSvnConfig(
            paths={"only": r"C:\only"},
        ),
    )


# ── 多项目场景 ──

@pytest.mark.asyncio
async def test_multi_no_project_errors(multi_config):
    """多项目时不指定 project 应报错。"""
    with patch.object(nimo.tools.tortoisesvn, "_config", multi_config):
        result = await nimo.tools.tortoisesvn.svn(command="log")
        assert result.success is False
        assert "多个项目" in result.error


@pytest.mark.asyncio
async def test_multi_by_project_name(multi_config):
    """通过 project 参数选择项目。"""
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"r100", b""))

    with patch.object(nimo.tools.tortoisesvn, "_config", multi_config):
        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_proc)) as mock_exec:
            result = await nimo.tools.tortoisesvn.svn(command="log", project="proj2")
            assert result.success is True
            call_args = mock_exec.call_args[0]
            assert any(r"D:\other\proj2" in arg for arg in call_args)


@pytest.mark.asyncio
async def test_multi_unknown_project(multi_config):
    """未知项目名应报错。"""
    with patch.object(nimo.tools.tortoisesvn, "_config", multi_config):
        result = await nimo.tools.tortoisesvn.svn(command="log", project="nope")
        assert result.success is False
        assert "未知项目" in result.error


# ── 单项目场景 ──

@pytest.mark.asyncio
async def test_single_auto_pick(single_config):
    """单项目时自动匹配，无需指定 project。"""
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"r12345", b""))

    with patch.object(nimo.tools.tortoisesvn, "_config", single_config):
        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_proc)) as mock_exec:
            result = await nimo.tools.tortoisesvn.svn(command="log")
            assert result.success is True
            call_args = mock_exec.call_args[0]
            assert any(r"C:\only" in arg for arg in call_args)


# ── 通用场景 ──

@pytest.mark.asyncio
async def test_explicit_path_wins(multi_config):
    """显式 path 优先级最高。"""
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"r200", b""))

    with patch.object(nimo.tools.tortoisesvn, "_config", multi_config):
        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_proc)) as mock_exec:
            result = await nimo.tools.tortoisesvn.svn(command="log", path=r"E:\explicit", project="proj1")
            assert result.success is True
            call_args = mock_exec.call_args[0]
            assert any(r"E:\explicit" in arg for arg in call_args)


@pytest.mark.asyncio
async def test_no_config():
    """无配置时报错。"""
    with patch.object(nimo.tools.tortoisesvn, "_config", None):
        result = await nimo.tools.tortoisesvn.svn(command="log")
        assert result.success is False
        assert "未配置" in result.error


@pytest.mark.asyncio
async def test_diff(multi_config):
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"@@ -1,3 +1,4 @@", b""))

    with patch.object(nimo.tools.tortoisesvn, "_config", multi_config):
        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_proc)):
            result = await nimo.tools.tortoisesvn.svn(
                command="diff", project="proj1", extra_args=["-r", "100:101"]
            )
            assert result.success is True


@pytest.mark.asyncio
async def test_error_return(multi_config):
    mock_proc = MagicMock()
    mock_proc.returncode = 1
    mock_proc.communicate = AsyncMock(return_value=(b"", b"svn: E155007: not a working copy"))

    with patch.object(nimo.tools.tortoisesvn, "_config", multi_config):
        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_proc)):
            result = await nimo.tools.tortoisesvn.svn(command="log", project="proj1")
            assert result.success is False
            assert "not a working copy" in result.error


@pytest.mark.asyncio
async def test_binary_not_found(multi_config):
    with patch.object(nimo.tools.tortoisesvn, "_config", multi_config):
        with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError("svn.exe")):
            result = await nimo.tools.tortoisesvn.svn(project="proj1", command="log")
            assert result.success is False
            assert "未找到" in result.error


# ── 校验测试 ──

def test_validate_unknown_command():
    result = nimo.tools.tortoisesvn._validate_args("rm", "")
    assert result is not None
    assert "不允许" in result


def test_validate_path_traversal():
    result = nimo.tools.tortoisesvn._validate_args("log", r"..\..\Windows")
    assert result is not None
    assert "路径遍历" in result


def test_validate_valid_commands():
    for cmd in nimo.tools.tortoisesvn._ALLOWED_COMMANDS:
        assert nimo.tools.tortoisesvn._validate_args(cmd, "") is None


# ── 路径解析测试 ──

def test_resolve_single_auto():
    c = Config(
        llm=MagicMock(), tapd=MagicMock(),
        tortoisesvn=TortoiseSvnConfig(paths={"only": r"C:\only"})
    )
    with patch.object(nimo.tools.tortoisesvn, "_config", c):
        p, err = nimo.tools.tortoisesvn._resolve_path("", "")
        assert p == r"C:\only"
        assert err is None


def test_resolve_multi_no_project():
    c = Config(
        llm=MagicMock(), tapd=MagicMock(),
        tortoisesvn=TortoiseSvnConfig(paths={"a": r"C:\a", "b": r"C:\b"})
    )
    with patch.object(nimo.tools.tortoisesvn, "_config", c):
        p, err = nimo.tools.tortoisesvn._resolve_path("", "")
        assert p == ""
        assert "多个项目" in err


def test_resolve_explicit_path():
    with patch.object(nimo.tools.tortoisesvn, "_config", None):
        p, err = nimo.tools.tortoisesvn._resolve_path(r"E:\x", "")
        assert p == r"E:\x"
        assert err is None
