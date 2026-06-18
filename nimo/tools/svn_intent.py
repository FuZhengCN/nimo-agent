"""svn_op：意图级 SVN 工具，委托给 ExecutionEngine 执行。"""
import logging
from nimo.tools.registry import register_tool, ToolResult
from nimo.engine import ExecutionEngine, Intent

logger = logging.getLogger(__name__)


@register_tool(
    name="svn_op",
    description=(
        "执行 SVN 版本控制操作（推荐使用）。"
        "常用操作：log=提交记录, diff=差异对比, blame=逐行追溯, "
        "update=更新工作副本, commit=提交更改, checkout=检出仓库, "
        "add=添加文件, revert=还原, cleanup=清理, info=仓库信息, "
        "switch=切换分支, merge=合并, lock/unlock=锁定/解锁, "
        "rename/remove=文件操作, import/export=导入/导出, repocreate=创建仓库。"
        "path 和 project 可选，不传则自动使用默认项目。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "SVN 操作名",
                "enum": [
                    "log", "diff", "blame", "update", "commit", "checkout",
                    "add", "revert", "cleanup", "resolve", "switch", "merge",
                    "relocate", "lock", "unlock", "rename", "remove",
                    "import", "export", "properties", "info", "repocreate",
                ],
            },
            "path": {
                "type": "string",
                "description": "工作副本路径。优先级最高，传了就不需要 project",
            },
            "project": {
                "type": "string",
                "description": "项目名，对应配置文件中的项目别名。不传则用默认项目",
            },
            "url": {
                "type": "string",
                "description": "仓库 URL，仅 checkout/switch/import/export 等需要",
            },
            "extra": {
                "type": "object",
                "description": (
                    "额外参数。log 常用：{\"limit\": 10, \"search\": \"关键词\"}。"
                    "diff 常用：{\"revision\": \"r123:124\"}。"
                    "commit 常用：{\"message\": \"提交信息\"}。"
                ),
            },
        },
        "required": ["action"],
    },
)
async def svn_op(
    action: str,
    path: str = "",
    project: str = "",
    url: str = "",
    extra: dict | None = None,
) -> ToolResult:
    engine = ExecutionEngine.get_instance()
    params = {}
    for key, val in locals().items():
        if key != "action" and val:
            params[key] = val
    intent = Intent(tool="svn", action=action, params=params)
    return await engine.execute(intent)
