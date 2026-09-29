from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, ClassVar

from pydantic import BaseModel


@dataclass(frozen=True)
class ToolContext:
    """Runtime values the runner injects into async plugins.

    These are not tool arguments. The model does not supply them.
    """

    user_id: str = ""
    run_id: str = ""
    trace_id: str = ""
    a2a_url: str = ""


class ToolPlugin(ABC):
    """Abstract base class for a tool plugin.

    Every tool plugin **must** define the following class variables:

    * ``name`` — unique tool identifier (used for ``@tool`` name and LLM binding).
    * ``description`` — LLM-facing description of what the tool does.
    * ``args_schema`` — a :class:`pydantic.BaseModel` subclass that defines
      the tool's input parameters.

    Subclasses **must** implement :meth:`execute`, which receives the validated
    arguments as keyword arguments and returns a JSON-formatted result string.

    Example::

        class MyTool(ToolPlugin):
            name = "my_tool"
            description = "Does something useful."
            args_schema = MyToolInput

            def execute(self, **kwargs: Any) -> str:
                return json.dumps({"result": kwargs["param"] * 2})
    """

    name: ClassVar[str]
    description: ClassVar[str]
    args_schema: ClassVar[type[BaseModel]]
    # Async plugins are awaited by SkillRunner. Sync plugins keep execute().
    is_async: ClassVar[bool] = False

    @staticmethod
    def _format_error(message: str, **extra: Any) -> str:
        """Format a consistent error response JSON string.

        All plugin error returns should use this helper so the stagnation
        detector and runner consistently recognize failures via the
        ``"is_error": True`` and ``"error"`` keys.

        Args:
            message: Human-readable error message.
            **extra: Additional key-value pairs to include in the error JSON.

        Returns:
            A JSON string with ``{"error": message, "is_error": True, ...}``.
        """
        return json.dumps({"error": message, "is_error": True, **extra}, ensure_ascii=False)

    @abstractmethod
    def execute(self, **kwargs: Any) -> str:
        """Execute the tool with validated arguments.

        Args:
            **kwargs: The tool arguments as keyword arguments. The keys match
                the fields of ``args_schema``.

        Returns:
            A JSON-encoded string representing the result.
        """
        ...

    async def aexecute(self, ctx: ToolContext, **kwargs: Any) -> str:
        """Execute an async plugin.

        SkillRunner calls this instead of :meth:`execute` when ``is_async``
        is true. Sync plugins never reach this method.
        """
        raise NotImplementedError(
            f"{type(self).__name__} is not an async tool plugin"
        )
