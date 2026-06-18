"""tapd_query：意图级 TAPD 工具，委托给 ExecutionEngine 执行。"""
import logging
from nimo.tools.registry import register_tool, ToolResult
from nimo.engine import ExecutionEngine, Intent

logger = logging.getLogger(__name__)


@register_tool(
    name="tapd_query",
    description=(
        "执行 TAPD 操作（推荐使用）。可用操作："
        "workspace_list=项目列表, "
        "story_list=需求列表, story_show=需求详情, story_create=创建需求, story_count=需求统计, "
        "task_list=任务列表, task_show=任务详情, task_create=创建任务, "
        "bug_list=缺陷列表, bug_show=缺陷详情, bug_create=创建缺陷, "
        "timesheet_list=工时列表, timesheet_add=填工时, "
        "iteration_list=迭代列表, iteration_create=创建迭代, "
        "comment_list=评论列表, comment_add=添加评论。"
        "查工时/需求/任务/缺陷时，不传 workspace_id 会自动遍历全部项目，无需手动先查项目列表。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "操作名，如 timesheet_list, story_list, story_create, task_show, bug_list 等",
                "enum": [
                    "workspace_list",
                    "story_list", "story_show", "story_create", "story_update", "story_count",
                    "task_list", "task_show", "task_create", "task_update",
                    "bug_list", "bug_show", "bug_create", "bug_update",
                    "timesheet_list", "timesheet_add",
                    "iteration_list", "iteration_create",
                    "comment_list", "comment_add",
                ],
            },
            "workspace_id": {
                "type": "string",
                "description": "项目ID。不传时查询类操作自动遍历全部项目",
            },
            "owner": {
                "type": "string",
                "description": "按人员中文名筛选，如 傅政。仅 timesheet_list/task_list/story_list/bug_list 有效",
            },
            "entity_id": {
                "type": "string",
                "description": "实体ID，show/update 操作用。传此参数时直接操作，不遍历项目",
            },
            "entity_type": {
                "type": "string",
                "description": "实体类型（story/task/bug），timesheet_add 时必填",
                "enum": ["story", "task", "bug"],
            },
            "name": {
                "type": "string",
                "description": "名称，create/update 操作用",
            },
            "description": {
                "type": "string",
                "description": "描述，create/update 操作用",
            },
            "date": {
                "type": "string",
                "description": "日期（YYYY-MM-DD），timesheet 操作用。不传默认当天",
            },
            "timespent": {
                "type": "string",
                "description": "工时（小时），timesheet_add 用",
            },
            "remark": {
                "type": "string",
                "description": "备注，timesheet_add 用",
            },
            "status": {
                "type": "string",
                "description": "状态，create/update 操作用",
            },
            "iteration_id": {
                "type": "string",
                "description": "迭代ID，list 操作用",
            },
            "limit": {
                "type": "integer",
                "description": "返回条数限制",
            },
        },
        "required": ["action"],
    },
)
async def tapd_query(
    action: str,
    workspace_id: str = "",
    owner: str = "",
    entity_id: str = "",
    entity_type: str = "",
    name: str = "",
    description: str = "",
    date: str = "",
    timespent: str = "",
    remark: str = "",
    status: str = "",
    iteration_id: str = "",
    limit: int = 0,
) -> ToolResult:
    engine = ExecutionEngine.get_instance()
    params = {}
    for key, val in locals().items():
        if key != "action" and val:
            params[key] = val
    intent = Intent(tool="tapd", action=action, params=params)
    return await engine.execute(intent)
