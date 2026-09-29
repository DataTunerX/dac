"""Stateless A2A message/send: one user message, collected reply text."""

from __future__ import annotations

import json
import logging
import os
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

logger = logging.getLogger(__name__)

_PROGRESS = "[[DAC_PROGRESS]]"
_EXECUTION_FLOW = "[[DAC_EXECUTION_FLOW]] "
_ANSWER = "[[DAC_ANSWER]] "
_SUMMARY = "[[DAC_SUMMARY]] "
_FAILED_STATES = frozenset({"failed", "canceled", "rejected"})


class A2aChatError(Exception):
    """The remote A2A call failed or returned nothing usable."""


def reduce_frames(chunks: list[str]) -> str:
    """Turn streamed artifact/message text into the visible reply.

    Drops DAC progress and execution-flow frames. ``[[DAC_ANSWER]]`` keeps
    only ``final_answer`` payload text. A ``[[DAC_SUMMARY]]`` frame replaces
    the collected body, matching the orchestrator's preference.
    """
    buf = ""
    lines: list[str] = []
    for chunk in chunks:
        if not chunk:
            continue
        buf += chunk
        while "\n" in buf:
            line, buf = buf.split("\n", 1)
            lines.append(line)
    if buf.strip():
        lines.append(buf)

    pieces: list[str] = []
    summary: str | None = None
    for line in lines:
        piece, summary_update = _visible_line(line)
        if summary_update is not None:
            summary = summary_update
            continue
        if piece:
            pieces.append(piece)
    if summary is not None:
        return summary.strip()
    return "\n".join(pieces).strip()


def _visible_line(line: str) -> tuple[str, str | None]:
    """Return ``(visible_text, summary)``.

    ``summary`` is set only for a parsed DAC_SUMMARY frame. Progress and
    execution-flow lines contribute neither.
    """
    text = line.strip()
    if not text:
        return "", None
    if text.startswith(_PROGRESS) or text.startswith(_EXECUTION_FLOW.strip()):
        return "", None
    flow_at = text.find(_EXECUTION_FLOW)
    if flow_at >= 0:
        text = text[:flow_at].strip()
        if not text:
            return "", None
    if text.startswith(_ANSWER.strip()):
        return _answer_payload_text(text), None
    if text.startswith(_SUMMARY.strip()):
        summary = _summary_payload_text(text)
        if summary is None:
            return "", None
        return "", summary
    return text, None


def _answer_payload_text(frame: str) -> str:
    payload = _frame_json(frame, _ANSWER.strip())
    if not isinstance(payload, dict):
        return ""
    if str(payload.get("event") or "").strip() != "final_answer":
        return ""
    body = payload.get("payload") or {}
    if not isinstance(body, dict):
        return ""
    return str(body.get("text") or "").strip()


def _summary_payload_text(frame: str) -> str | None:
    payload = _frame_json(frame, _SUMMARY.strip())
    if not isinstance(payload, dict) or "summary" not in payload:
        return None
    return str(payload.get("summary") or "").strip()


def _frame_json(frame: str, prefix: str) -> Any:
    raw = frame.strip()
    if raw.startswith(prefix):
        raw = raw[len(prefix):].strip()
    elif raw.startswith(prefix + " "):
        raw = raw[len(prefix):].strip()
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def _chunk_data(chunk: Any) -> dict[str, Any]:
    if isinstance(chunk, dict):
        return chunk
    dump = getattr(chunk, "model_dump", None)
    if callable(dump):
        data = dump(mode="json", exclude_none=True)
        if isinstance(data, dict):
            return data
    return {}


def _part_text(parts: Any) -> str:
    if not isinstance(parts, list):
        return ""
    texts: list[str] = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        kind = part.get("kind") or part.get("type")
        if kind not in (None, "text"):
            continue
        if part.get("text") is None:
            continue
        texts.append(str(part.get("text")))
    return "".join(texts)


def split_stream_chunk(chunk: Any) -> tuple[str, str, str]:
    """Split one stream event into artifact text, message text, and task state.

    Artifact text is preferred when assembling the reply. Message text is the
    fallback for agents that answer with a Message instead of an artifact.
    """
    data = _chunk_data(chunk)
    error = data.get("error")
    if error:
        if isinstance(error, dict):
            message = str(error.get("message") or error)
        else:
            message = str(error)
        raise A2aChatError(message)

    result = data.get("result")
    if not isinstance(result, dict):
        return "", "", ""

    kind = str(result.get("kind") or "")
    if kind == "artifact-update":
        artifact = result.get("artifact")
        if not isinstance(artifact, dict):
            return "", "", ""
        return _part_text(artifact.get("parts")), "", ""

    if kind == "message":
        return "", _part_text(result.get("parts")), ""

    if kind == "status-update":
        status = result.get("status") if isinstance(result.get("status"), dict) else {}
        message = status.get("message") if isinstance(status.get("message"), dict) else {}
        state = str(status.get("state") or "")
        return "", _part_text(message.get("parts")), state

    if kind == "task":
        status = result.get("status") if isinstance(result.get("status"), dict) else {}
        state = str(status.get("state") or "")
        message = status.get("message") if isinstance(status.get("message"), dict) else {}
        artifact_text = ""
        artifacts = result.get("artifacts")
        if isinstance(artifacts, list):
            chunks: list[str] = []
            for artifact in artifacts:
                if isinstance(artifact, dict):
                    chunks.append(_part_text(artifact.get("parts")))
            artifact_text = "".join(chunks)
        return artifact_text, _part_text(message.get("parts")), state

    return "", "", ""


def assemble_reply(
    *,
    artifact_chunks: list[str],
    message_chunks: list[str],
    saw_artifact_event: bool,
) -> str:
    """Prefer streamed artifacts. Fall back to message parts, then a task snapshot."""
    if saw_artifact_event:
        text = reduce_frames(artifact_chunks)
        if text:
            return text
    return reduce_frames(message_chunks)


def _timeout_seconds() -> float:
    raw = os.getenv("A2A_REQUEST_TIMEOUT", "180").strip()
    try:
        value = float(raw)
    except ValueError:
        return 180.0
    return value if value > 0 else 180.0


def _max_chars() -> int:
    raw = os.getenv("A2A_MAX_CHARS", "20000").strip()
    try:
        value = int(raw)
    except ValueError:
        return 20000
    return value if value > 0 else 20000


def validate_a2a_url(url: str) -> str:
    """Return a stripped http(s) base URL, or raise ``A2aChatError``."""
    cleaned = (url or "").strip().rstrip("/")
    parsed = urlparse(cleaned)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise A2aChatError(f"a2a.url must be an http(s) URL, got {url!r}")
    return cleaned


async def run_a2a_chat(
    *,
    base_url: str,
    message: str,
    user_id: str = "",
    run_id: str = "",
    trace_id: str = "",
) -> str:
    """Send one user message and return the collected visible reply.

    Each call starts a new A2A task. Nothing from a previous call is sent.
    """
    url = validate_a2a_url(base_url)
    text = (message or "").strip()
    if not text:
        raise A2aChatError("message is required")

    import httpx
    from a2a.client import A2ACardResolver, A2AClient
    from a2a.types import MessageSendParams, SendStreamingMessageRequest

    timeout = httpx.Timeout(_timeout_seconds(), connect=10.0)
    payload: dict[str, Any] = {
        "message": {
            "role": "user",
            "parts": [{"type": "text", "text": text}],
            "messageId": uuid4().hex,
        },
        "metadata": {
            "user_id": user_id,
            "run_id": run_id,
            "trace_id": trace_id,
            "skip_history_write": True,
        },
    }

    artifact_chunks: list[str] = []
    message_chunks: list[str] = []
    saw_artifact_event = False
    task_artifacts: list[str] = []
    last_state = ""

    async with httpx.AsyncClient(timeout=timeout) as httpx_client:
        resolver = A2ACardResolver(httpx_client=httpx_client, base_url=url)
        try:
            card = await resolver.get_agent_card()
        except Exception as exc:
            raise A2aChatError(f"failed to fetch agent card from {url}: {exc}") from exc

        card_url = str(getattr(card, "url", "") or "").rstrip("/")
        if card_url and card_url != url:
            logger.info(
                "agent card url %s differs from skill a2a.url %s; sending to the skill url",
                card_url,
                url,
            )
        # The card often advertises an in-cluster address. The skill's a2a.url
        # is the address this process can actually reach.
        client = A2AClient(httpx_client=httpx_client, agent_card=card, url=url)
        request = SendStreamingMessageRequest(
            id=uuid4().hex,
            params=MessageSendParams(**payload),
        )
        try:
            stream = client.send_message_streaming(request)
            async for chunk in stream:
                artifact_text, message_text, state = split_stream_chunk(chunk)
                data = _chunk_data(chunk)
                result = data.get("result") if isinstance(data.get("result"), dict) else {}
                kind = str(result.get("kind") or "")
                if state:
                    last_state = state
                if kind == "artifact-update" and artifact_text:
                    saw_artifact_event = True
                    artifact_chunks.append(artifact_text)
                elif kind == "task" and artifact_text:
                    task_artifacts.append(artifact_text)
                if message_text:
                    message_chunks.append(message_text)
        except A2aChatError:
            raise
        except Exception as exc:
            raise A2aChatError(f"A2A request failed: {exc}") from exc

    if not saw_artifact_event and task_artifacts:
        artifact_chunks = task_artifacts
        saw_artifact_event = True

    reply = assemble_reply(
        artifact_chunks=artifact_chunks,
        message_chunks=message_chunks,
        saw_artifact_event=saw_artifact_event,
    )
    if not reply:
        if last_state in _FAILED_STATES:
            raise A2aChatError(f"A2A task ended with state {last_state}")
        raise A2aChatError("A2A agent returned no text")

    limit = _max_chars()
    if len(reply) > limit:
        return reply[:limit]
    return reply
