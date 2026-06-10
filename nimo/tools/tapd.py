import logging
import httpx
from nimo.config import Config
from nimo.tools.registry import register_tool, ToolResult

logger = logging.getLogger(__name__)

_config: Config | None = None
_client: httpx.AsyncClient | None = None


def init_tapd(config: Config) -> None:
    global _config, _client
    _config = config
    _client = httpx.AsyncClient(
        base_url=config.tapd.api_base,
        headers={"Authorization": f"Bearer {config.tapd.access_token}"},
        timeout=30.0,
    )


async def _api_get(path: str, params: dict | None = None) -> dict:
    if _client is None:
        raise RuntimeError("TAPD 客户端未初始化，请先调用 init_tapd()")
    resp = await _client.get(path, params=params)
    resp.raise_for_status()
    return resp.json()


async def _api_post(path: str, body: dict | None = None) -> dict:
    if _client is None:
        raise RuntimeError("TAPD 客户端未初始化，请先调用 init_tapd()")
    resp = await _client.post(path, data=body)
    resp.raise_for_status()
    return resp.json()


@register_tool(
    name="tapd_list_projects",
    description="获取当前用户在 TAPD 中有权限参与的项目列表。返回项目名称、ID 和状态。",
    parameters={
        "type": "object",
        "properties": {},
    },
)
async def tapd_list_projects() -> ToolResult:
    try:
        data = await _api_get("/workspaces/user_participant_projects", params={
            "nick": _config.tapd.nick,
            "company_id": _config.tapd.company_id,
        })
        if data.get("status") != 1:
            return ToolResult(success=False, error=f"TAPD 返回错误：{data.get('info', '未知错误')}")
        return ToolResult(success=True, data=data["data"])
    except Exception as e:
        logger.exception("查项目列表失败")
        return ToolResult(success=False, error=str(e))


@register_tool(
    name="tapd_add_workhour",
    description="为 TAPD 中的需求（story）、任务（task）或缺陷（bug）填写工时记录。同一对象同一人同一天不可重复填写。",
    parameters={
        "type": "object",
        "properties": {
            "workspace_id": {"type": "integer", "description": "项目 ID"},
            "entity_type": {
                "type": "string",
                "enum": ["story", "task", "bug"],
                "description": "对象类型",
            },
            "entity_id": {"type": "integer", "description": "需求/任务/缺陷的 ID"},
            "timespent": {"type": "string", "description": "工时（小时），如 '2.5'"},
            "spentdate": {"type": "string", "description": "日期，格式 YYYY-MM-DD"},
            "memo": {"type": "string", "description": "工时内容说明"},
        },
        "required": ["workspace_id", "entity_type", "entity_id", "timespent"],
    },
)
async def tapd_add_workhour(
    workspace_id: int,
    entity_type: str,
    entity_id: int,
    timespent: str,
    spentdate: str = "",
    memo: str = "",
) -> ToolResult:
    try:
        body = {
            "workspace_id": workspace_id,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "timespent": timespent,
            "owner": _config.tapd.owner,
        }
        if spentdate:
            body["spentdate"] = spentdate
        if memo:
            body["memo"] = memo

        data = await _api_post("/timesheets", body=body)
        if data.get("status") != 1:
            return ToolResult(success=False, error=f"TAPD 返回错误：{data.get('info', '未知错误')}")
        return ToolResult(success=True, data=data["data"])
    except Exception as e:
        logger.exception("填工时失败")
        return ToolResult(success=False, error=str(e))
