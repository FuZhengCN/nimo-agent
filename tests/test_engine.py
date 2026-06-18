"""ExecutionEngine 测试套件——覆盖 direct / for_each_workspace / 失败路径 / SVN。"""
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from nimo.config import Config, LLMConfig, TapdConfig, TortoiseSvnConfig
from nimo.engine import ExecutionEngine, Intent


@pytest.fixture(autouse=True)
def reset_engine():
    """每个测试前重置 ExecutionEngine 单例，保证隔离。"""
    ExecutionEngine.reset()


@pytest.fixture
def sample_config():
    """提供最小可用的 Config 实例。"""
    return Config(
        llm=LLMConfig(
            api_key="sk-test", base_url="https://api.deepseek.com",
            model="deepseek-chat", max_tool_rounds=5, history_rounds=10,
        ),
        tapd=TapdConfig(
            api_base="https://api.tapd.cn", access_token="token123",
            nick="testuser", company_id="12345", owner="testuser",
        ),
    )


# ---------------------------------------------------------------------------
# Direct 模式测试
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_direct_timesheet_with_workspace_id(sample_config):
    """有 workspace_id -> direct 模式，单次执行。"""
    engine = ExecutionEngine.get_instance()
    engine.init(sample_config)

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b'[{"id":"1"}]', b""))

    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_proc)):
        result = await engine.execute(Intent(
            tool="tapd", action="timesheet_list",
            params={"workspace_id": "755", "owner": "傅政"},
        ))
    assert result.success is True
    assert "1" in str(result.data)


@pytest.mark.asyncio
async def test_direct_workspace_list(sample_config):
    """workspace_list 始终 direct 模式。"""
    engine = ExecutionEngine.get_instance()
    engine.init(sample_config)

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(
        b'[{"id":"755","name":"TAPD"},{"id":"756","name":"Proj2"}]', b"",
    ))

    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_proc)):
        result = await engine.execute(Intent(
            tool="tapd", action="workspace_list", params={},
        ))
    assert result.success is True
    assert "TAPD" in str(result.data)


# ---------------------------------------------------------------------------
# for_each_workspace 模式测试
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_for_each_workspace_success(sample_config):
    """无 workspace_id + timesheet_list -> for_each_workspace 模式。"""
    engine = ExecutionEngine.get_instance()
    engine.init(sample_config)

    ws_list_proc = MagicMock()
    ws_list_proc.returncode = 0
    ws_list_proc.communicate = AsyncMock(return_value=(
        b'[{"id":"755","name":"TAPD"},{"id":"756","name":"Proj2"}]', b"",
    ))

    ts1_proc = MagicMock()
    ts1_proc.returncode = 0
    ts1_proc.communicate = AsyncMock(return_value=(b'[{"id":"t1"}]', b""))

    ts2_proc = MagicMock()
    ts2_proc.returncode = 0
    ts2_proc.communicate = AsyncMock(return_value=(b'[{"id":"t2"}]', b""))

    mock_create = AsyncMock(side_effect=[ws_list_proc, ts1_proc, ts2_proc])

    with patch("asyncio.create_subprocess_exec", new=mock_create):
        result = await engine.execute(Intent(
            tool="tapd", action="timesheet_list",
            params={"owner": "傅政"},
        ))
    assert result.success is True
    items = result.data["items"]
    assert len(items) == 2
    assert items[0]["workspace_name"] == "TAPD"
    assert items[1]["workspace_name"] == "Proj2"


@pytest.mark.asyncio
async def test_for_each_workspace_partial_failure(sample_config):
    """部分 workspace 失败 -> success=True，errors 列出失败项。"""
    engine = ExecutionEngine.get_instance()
    engine.init(sample_config)

    ws_list_proc = MagicMock()
    ws_list_proc.returncode = 0
    ws_list_proc.communicate = AsyncMock(return_value=(
        b'[{"id":"755","name":"A"},{"id":"756","name":"B"}]', b"",
    ))

    ts1_proc = MagicMock()
    ts1_proc.returncode = 0
    ts1_proc.communicate = AsyncMock(return_value=(b'[{"id":"t1"}]', b""))

    ts2_proc = MagicMock()
    ts2_proc.returncode = 1
    ts2_proc.communicate = AsyncMock(return_value=(b"", b"timeout"))

    mock_create = AsyncMock(side_effect=[ws_list_proc, ts1_proc, ts2_proc])

    with patch("asyncio.create_subprocess_exec", new=mock_create):
        result = await engine.execute(Intent(
            tool="tapd", action="timesheet_list",
            params={"owner": "傅政"},
        ))
    assert result.success is True
    assert len(result.data["items"]) == 1
    assert len(result.data["errors"]) == 1


@pytest.mark.asyncio
async def test_for_each_workspace_all_failure(sample_config):
    """全部 workspace 失败 -> success=False。"""
    engine = ExecutionEngine.get_instance()
    engine.init(sample_config)

    ws_list_proc = MagicMock()
    ws_list_proc.returncode = 0
    ws_list_proc.communicate = AsyncMock(return_value=(
        b'[{"id":"755","name":"A"}]', b"",
    ))

    ts1_proc = MagicMock()
    ts1_proc.returncode = 1
    ts1_proc.communicate = AsyncMock(return_value=(b"", b"auth error"))

    mock_create = AsyncMock(side_effect=[ws_list_proc, ts1_proc])

    with patch("asyncio.create_subprocess_exec", new=mock_create):
        result = await engine.execute(Intent(
            tool="tapd", action="timesheet_list",
            params={"owner": "傅政"},
        ))
    assert result.success is False
    assert result.data is None
    assert "auth error" in result.error


# ---------------------------------------------------------------------------
# 错误路径测试
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unknown_action(sample_config):
    """未知 action -> 错误。"""
    engine = ExecutionEngine.get_instance()
    engine.init(sample_config)

    result = await engine.execute(Intent(
        tool="tapd", action="nonexistent_op",
        params={"workspace_id": "755"},
    ))
    assert result.success is False
    assert "未知" in result.error


@pytest.mark.asyncio
async def test_missing_workspace_id_for_create(sample_config):
    """非查询 action（如 story_create）不传 workspace_id -> 错误。"""
    engine = ExecutionEngine.get_instance()
    engine.init(sample_config)

    result = await engine.execute(Intent(
        tool="tapd", action="story_create",
        params={"name": "test"},
    ))
    assert result.success is False
    assert "workspace_id" in result.error


@pytest.mark.asyncio
async def test_for_each_workspace_list_fails(sample_config):
    """workspace list 本身失败 -> 直接返回失败。"""
    engine = ExecutionEngine.get_instance()
    engine.init(sample_config)

    mock_proc = MagicMock()
    mock_proc.returncode = 1
    mock_proc.communicate = AsyncMock(return_value=(b"", b"network error"))

    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_proc)):
        result = await engine.execute(Intent(
            tool="tapd", action="timesheet_list",
            params={"owner": "傅政"},
        ))
    assert result.success is False
    assert "network error" in result.error


@pytest.mark.asyncio
async def test_run_tapd_file_not_found(sample_config):
    """tapd.exe 不存在 -> FileNotFoundError 被捕获并返回友好信息。"""
    engine = ExecutionEngine.get_instance()
    engine.init(sample_config)

    with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError):
        success, stdout, error = await engine._run_tapd(["workspace", "list"])
    assert success is False
    assert "未找到" in error


# ---------------------------------------------------------------------------
# SVN 测试
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_svn_direct(sample_config):
    """SVN 意图始终 direct 模式。"""
    sample_config.tortoisesvn = TortoiseSvnConfig(paths={"default": "/tmp/repo"})

    engine = ExecutionEngine.get_instance()
    engine.init(sample_config)

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"r123 | user | log msg", b""))

    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_proc)):
        result = await engine.execute(Intent(
            tool="svn", action="log",
            params={"project": "default", "extra": {"limit": 5}},
        ))
    assert result.success is True
    assert "r123" in str(result.data)
