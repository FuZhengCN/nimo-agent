import importlib
import logging
import pkgutil

from nimo.tools.registry import ToolRegistry, ToolResult, register_tool

logger = logging.getLogger(__name__)

# 自动发现并加载所有工具模块（不以 _ 开头的非 registry 模块）
for _loader, _name, _is_pkg in pkgutil.iter_modules(__path__):
    if not _name.startswith("_") and _name != "registry":
        try:
            importlib.import_module(f"{__name__}.{_name}")
        except Exception:
            logger.warning("工具模块 %s 加载失败，跳过", _name, exc_info=True)
