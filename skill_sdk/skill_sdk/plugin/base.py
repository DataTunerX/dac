from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar

from pydantic import BaseModel


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
