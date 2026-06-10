import pytest
from unittest.mock import patch, AsyncMock
from nimo.config import Config, LLMConfig, TapdConfig

# Module-level import triggers @register_tool once. Tools stay registered for all tests.
import nimo.tools.tapd


@pytest.fixture
def sample_config():
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


@pytest.mark.asyncio
async def test_list_projects_success(sample_config):
    api_response = {
        "status": 1,
        "data": [
            {"Workspace": {"id": "755", "name": "TAPD平台", "status": "normal"}},
            {"Workspace": {"id": "10158231", "name": "游戏项目A", "status": "normal"}},
        ],
        "info": "success",
    }

    with patch.object(nimo.tools.tapd, "_config", sample_config):
        with patch.object(nimo.tools.tapd, "_api_get", new=AsyncMock(return_value=api_response)):
            result = await nimo.tools.tapd.tapd_list_projects()
            assert result.success is True
            assert len(result.data) == 2
            assert result.data[0]["Workspace"]["name"] == "TAPD平台"


@pytest.mark.asyncio
async def test_add_workhour_success(sample_config):
    api_response = {"status": 1, "data": {"Timesheet": {"id": "1001"}}, "info": "success"}

    with patch.object(nimo.tools.tapd, "_config", sample_config):
        with patch.object(nimo.tools.tapd, "_api_post", new=AsyncMock(return_value=api_response)):
            result = await nimo.tools.tapd.tapd_add_workhour(
                workspace_id=10158231,
                entity_type="story",
                entity_id=1001,
                timespent="2",
                spentdate="2026-06-10",
                memo="需求评审",
            )
            assert result.success is True
            assert result.data["Timesheet"]["id"] == "1001"


@pytest.mark.asyncio
async def test_add_workhour_api_error(sample_config):
    api_response = {"status": 0, "info": "参数错误", "data": ""}

    with patch.object(nimo.tools.tapd, "_config", sample_config):
        with patch.object(nimo.tools.tapd, "_api_post", new=AsyncMock(return_value=api_response)):
            result = await nimo.tools.tapd.tapd_add_workhour(
                workspace_id=10158231,
                entity_type="story",
                entity_id=1001,
                timespent="2",
            )
            assert result.success is False
            assert "参数错误" in result.error
