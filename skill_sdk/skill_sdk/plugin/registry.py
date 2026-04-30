from __future__ import annotations

import logging
import pkgutil
from typing import Any

from langchain_core.tools import tool as lc_tool

from skill_sdk.plugin.base import ToolPlugin

logger = logging.getLogger(__name__)


def _is_concrete_tool_plugin(cls: type) -> bool:
    """Return True if *cls* is a concrete :class:`ToolPlugin` subclass
    (not the ABC itself)."""
    if cls is ToolPlugin:
        return False
    return isinstance(cls, type) and issubclass(cls, ToolPlugin)


def _make_langchain_tool(plugin_cls: type[ToolPlugin]):
    """Build a LangChain ``@tool`` wrapper from a ``ToolPlugin`` subclass.

    The returned function is a proper LangChain tool with the correct
    ``name``, ``description`` and ``args_schema``, suitable for passing to
    ``llm.bind_tools(...)``.
    """

    @lc_tool(plugin_cls.name, description=plugin_cls.description, args_schema=plugin_cls.args_schema)
    def _wrapped(**kwargs: Any) -> str:
        """Executed by the runner."""
        return plugin_cls().execute(**kwargs)

    return _wrapped


class ToolRegistry:
    """Central registry for :class:`ToolPlugin` subclasses.

    Supports both explicit registration and auto-discovery from a package.
    Once plugins are registered, call :meth:`to_langchain_tools` to get
    LangChain-compatible tool functions ready for ``llm.bind_tools(...)``.
    """

    def __init__(self) -> None:
        self._plugins: dict[str, type[ToolPlugin]] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, plugin_cls: type[ToolPlugin]) -> None:
        """Register a concrete :class:`ToolPlugin` subclass.

        Args:
            plugin_cls: The plugin class (not an instance).

        Raises:
            TypeError: If *plugin_cls* is not a concrete ``ToolPlugin`` subclass.
            ValueError: If another plugin with the same ``name`` is already
                registered.
        """
        if not _is_concrete_tool_plugin(plugin_cls):
            raise TypeError(
                f"{plugin_cls.__name__} is not a concrete ToolPlugin subclass"
            )
        name = plugin_cls.name
        if name in self._plugins:
            raise ValueError(
                f"A tool plugin with name {name!r} is already registered "
                f"({self._plugins[name].__name__})"
            )
        self._plugins[name] = plugin_cls
        logger.info("Registered tool plugin: %s (%s)", name, plugin_cls.__name__)

    def unregister(self, name: str) -> None:
        """Remove a previously registered plugin by name.

        Args:
            name: The plugin name to remove.
        """
        removed = self._plugins.pop(name, None)
        if removed is not None:
            logger.info("Unregistered tool plugin: %s (%s)", name, removed.__name__)

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def get(self, name: str) -> type[ToolPlugin] | None:
        """Look up a registered plugin by name.

        Args:
            name: The plugin name.

        Returns:
            The plugin class, or ``None`` if not found.
        """
        return self._plugins.get(name)

    def list_names(self) -> list[str]:
        """List the names of all registered plugins."""
        return list(self._plugins.keys())

    def __len__(self) -> int:
        return len(self._plugins)

    def __contains__(self, name: str) -> bool:
        return name in self._plugins

    # ------------------------------------------------------------------
    # Auto-discovery
    # ------------------------------------------------------------------

    def discover_package(self, package_name: str) -> None:
        """Scan a Python package for :class:`ToolPlugin` subclasses and
        register every concrete one found.

        Uses ``pkgutil.walk_packages`` so sub-packages are searched recursively.
        Only classes that are **concrete** (i.e. not the ABC itself) are
        registered.

        Args:
            package_name: Dotted package path, e.g. ``"skill_sdk.tool"``.

        Raises:
            ImportError: If the package cannot be imported.
        """
        import importlib

        parent = importlib.import_module(package_name)
        logger.info("Discovering ToolPlugin subclasses in package %r ...", package_name)

        count = 0
        for _importer, modname, _ispkg in pkgutil.walk_packages(
            path=getattr(parent, "__path__", []),
            prefix=f"{package_name}.",
            onerror=lambda name: logger.warning(
                "Failed to walk sub-package %r", name
            ),
        ):
            try:
                mod = importlib.import_module(modname)
            except Exception as exc:
                logger.debug("Skipping module %r (import error: %s)", modname, exc)
                continue

            for attr_name in dir(mod):
                obj = getattr(mod, attr_name, None)
                if _is_concrete_tool_plugin(obj):
                    # Avoid registering the same class from duplicate imports
                    if obj.name not in self._plugins:
                        self.register(obj)
                        count += 1

        logger.info(
            "Discovery finished: registered %d tool plugin(s) from %r",
            count,
            package_name,
        )

    # ------------------------------------------------------------------
    # LangChain integration
    # ------------------------------------------------------------------

    def to_langchain_tools(self) -> list:
        """Convert every registered plugin into a LangChain ``@tool``
        function.

        The returned list is suitable for ``llm.bind_tools(...)`` or
        appending to `SkillRunner._runner_tools`.

        Returns:
            A list of LangChain tool functions.
        """
        return [_make_langchain_tool(cls) for cls in self._plugins.values()]

    def reset(self) -> None:
        """Clear all registered plugins."""
        self._plugins.clear()
