import asyncio
import logging
from pathlib import Path
from nimo.config import Config
from nimo.tools.registry import register_tool, ToolResult, ToolRegistry

logger = logging.getLogger(__name__)

_config: Config | None = None

_SVN_EXE = str(Path(__file__).resolve().parent.parent.parent / "bin" / "svn.exe")
_SVNADMIN_EXE = str(Path(__file__).resolve().parent.parent.parent / "bin" / "svnadmin.exe")

_ALLOWED_COMMANDS = frozenset({
    "log", "diff", "blame", "update", "commit", "checkout", "add",
    "revert", "cleanup", "resolve", "switch", "merge", "relocate",
    "lock", "unlock", "rename", "remove", "import", "export",
    "properties", "info", "repocreate",
})

_URL_BEFORE_PATH = frozenset({"switch", "merge", "checkout", "import", "export"})

_READONLY_COMMANDS = frozenset({
    "log", "diff", "blame", "info", "properties",
})


def _is_url(s: str) -> bool:
    return s.startswith(("http://", "https://", "svn://", "svn+ssh://"))


def _validate_args(command: str, path: str) -> str | None:
    if command not in _ALLOWED_COMMANDS:
        return f"不允许的 SVN 命令：{command}"
    if path and not _is_url(path):
        if ".." in path.replace("/", "\\"):
            return f"路径包含路径遍历：{path}"
    return None


def _build_args(command: str, path: str, url: str, extra_args: list[str] | None) -> list[str]:
    if command == "repocreate":
        args = [_SVNADMIN_EXE, "create"]
    else:
        args = [_SVN_EXE, command]
    if extra_args:
        args.extend(extra_args)
    if command in _URL_BEFORE_PATH:
        if url:
            args.append(url)
        if path:
            args.append(path)
    elif _is_url(path):
        args.append(path)
    elif path:
        args.append(path)
    return args


def _resolve_path(path: str, project: str) -> tuple[str, str | None]:
    """解析路径，返回 (path, error)。
    优先级：显式 path > 项目名查找 > 仅一个项目时自动取 > 报错。"""
    if path:
        return path, None
    if not _config:
        return "", "未配置 SVN 项目，请在 config.yaml 的 tortoisesvn.paths 中配置"
    cfg = _config.tortoisesvn
    if project:
        if project in cfg.paths:
            return cfg.paths[project], None
        return "", f"未知项目：{project}，可用：{', '.join(cfg.paths.keys())}"
    if not cfg.paths:
        return "", "未配置 SVN 项目"
    if len(cfg.paths) == 1:
        return next(iter(cfg.paths.values())), None
    names = ', '.join(cfg.paths.keys())
    return "", f"有多个项目（{names}），请用 project 参数指定"


async def init_tortoisesvn(config: Config) -> None:
    global _config
    _config = config
    cfg = config.tortoisesvn
    projects = list(cfg.paths.keys())
    if projects:
        registry = ToolRegistry.get_instance()
        tool = registry._tools.get("svn")
        if tool:
            lines = [f"已配置 {len(projects)} 个项目："]
            for name, p in cfg.paths.items():
                lines.append(f"  {name}: {p}")
            tool.description += " " + "；".join(lines)


@register_tool(
    name="svn",
    description=(
        "执行 SVN 版本控制操作。"
        "常用命令：log=查看提交记录, diff=查看差异, blame=逐行追溯, info=仓库信息, "
        "update=更新工作副本, commit=提交更改, checkout=检出仓库, add=添加文件, revert=还原, "
        "cleanup=清理, switch=切换分支, merge=合并, lock/unlock=锁定/解锁, "
        "rename/remove=文件操作, import/export=导入/导出, repocreate=创建仓库。"
        "path 和 project 可选，不传则自动使用默认项目。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "SVN 命令名。查提交记录用 log，查差异用 diff，查谁改的用 blame，更新用 update",
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
            "extra_args": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "额外参数。log 常用：-l 条数, -r 版本范围, --search 关键词。"
                    "diff 常用：-r 版本范围。blame 常用：-r 版本范围。"
                    "commit 常用：-m 提交信息。update 常用：-r 版本号。"
                ),
            },
        },
        "required": ["command"],
    },
)
async def svn(
    command: str,
    path: str = "",
    project: str = "",
    url: str = "",
    extra_args: list[str] | None = None,
) -> ToolResult:
    resolved_path, path_error = _resolve_path(path, project)
    if path_error:
        return ToolResult(success=False, error=path_error)
    if error := _validate_args(command, resolved_path):
        return ToolResult(success=False, error=error)

    if _is_url(resolved_path) and command not in _READONLY_COMMANDS:
        return ToolResult(
            success=False,
            error=f"{command} 需要本地工作副本，但配置的是远端 URL",
        )

    try:
        args = _build_args(command, resolved_path, url, extra_args)
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        def _decode(data: bytes) -> str:
            for enc in ("gbk", "utf-8"):
                try:
                    return data.decode(enc)
                except UnicodeDecodeError:
                    continue
            return data.decode(errors="replace")

        if proc.returncode != 0:
            err_msg = (_decode(stderr) or _decode(stdout)).strip()
            return ToolResult(success=False, error=err_msg or f"svn 返回非零退出码 {proc.returncode}")
        return ToolResult(success=True, data=_decode(stdout).strip())
    except FileNotFoundError as e:
        return ToolResult(success=False, error=f"可执行文件未找到：{e}")
    except Exception as e:
        logger.exception("SVN 执行失败")
        return ToolResult(success=False, error=str(e))


ToolRegistry.get_instance().register_init(init_tortoisesvn)
