"""Stateless A2A conversation tool.

The server address comes from the skill's ``_meta.json`` (``a2a.url``),
which SkillRunner injects as ``ToolContext.a2a_url``. The model only
supplies the message.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, Field

from skill_sdk.plugin.base import ToolContext, ToolPlugin

logger = logging.getLogger(__name__)

A2A_CHAT_TOOL_NAME = "a2a_chat"


class A2aChatInput(BaseModel):
    """Input schema for ``a2a_chat``."""

    message: str = Field(
        description=(
            "发给当前 skill 所配置 A2A 服务的用户消息。"
            "服务器地址来自 skill 配置，不要在参数里填写 URL。"
        ),
    )


class A2aChatPlugin(ToolPlugin):
    """Send one message to the skill's A2A server and return the reply text."""

    name = A2A_CHAT_TOOL_NAME
    description = (
        "向当前 skill 配置的 A2A 服务发送一条消息，并返回对方回复的正文。"
        "每次调用都是一次新对话，不延续上一次的任务。"
        "参数只有 message。不要传入 URL。"
    )
    args_schema = A2aChatInput
    is_async = True

    def execute(self, **kwargs: Any) -> str:
        return self._format_error(
            "a2a_chat is async and must be executed by SkillRunner"
        )

    async def aexecute(self, ctx: ToolContext, **kwargs: Any) -> str:
        from skill_sdk.tool.a2a_conversation import A2aChatError, run_a2a_chat

        message = str(kwargs.get("message") or "").strip()
        url = str(ctx.a2a_url or "").strip()
        if not message:
            return self._format_error("message is required")
        if not url:
            return self._format_error("skill a2a.url is empty")

        try:
            text = await run_a2a_chat(
                base_url=url,
                message=message,
                user_id=ctx.user_id,
                run_id=ctx.run_id,
                trace_id=ctx.trace_id,
            )
        except A2aChatError as exc:
            logger.info("a2a_chat failed url=%s error=%s", url, exc)
            return self._format_error(str(exc), url=url)
        except Exception as exc:  # noqa: BLE001
            logger.exception("a2a_chat unexpected error")
            return self._format_error(f"A2A chat error: {exc}", url=url)

        return json.dumps(
            {"url": url, "text": text},
            ensure_ascii=False,
        )
