import argparse
import asyncio
import os
import sys
from typing import Any
from uuid import uuid4

import httpx
from a2a.client import A2ACardResolver, A2AClient
from a2a.types import MessageSendParams, SendStreamingMessageRequest

# python -m orchestrator_agent.a2a_client --url http://... -u UID -r RID -q "your question"

def _default_base_url() -> str:
    return os.getenv("A2A_AGENT_URL", "http://10.17.0.41:30100")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "A2A chat client: send --query once (non-interactive) or omit it for a REPL. "
            "Always sends user_id and run_id in message metadata."
        ),
    )
    parser.add_argument(
        "--user-id",
        "-u",
        default=os.getenv("A2A_USER_ID"),
        help="User ID for each message metadata (or set A2A_USER_ID).",
    )
    parser.add_argument(
        "--run-id",
        "-r",
        default=os.getenv("A2A_RUN_ID"),
        help="Run ID for each message metadata (or set A2A_RUN_ID).",
    )
    parser.add_argument(
        "--url",
        default=_default_base_url(),
        help="A2A agent server base URL (default: A2A_AGENT_URL env or built-in default).",
    )
    parser.add_argument(
        "--query",
        "-q",
        default=os.getenv("A2A_QUERY"),
        help=(
            "User message to send (streaming reply, then exit). "
            "If omitted, starts an interactive session. "
            "May also set A2A_QUERY."
        ),
    )
    ns = parser.parse_args(argv)
    if not ns.user_id or not ns.run_id:
        parser.error(
            "user_id and run_id are required: pass --user-id / --run-id "
            "or set A2A_USER_ID / A2A_RUN_ID in the environment.",
        )
    return ns


def print_welcome_message(
    user_id: str,
    run_id: str,
    base_url: str,
    *,
    initial_query: str | None,
) -> None:
    print("A2A chat client")
    print(f"  Server:  {base_url}")
    print(f"  user_id: {user_id}")
    print(f"  run_id:  {run_id}")
    if initial_query is not None:
        print(f"  query:   {initial_query}")
        print("Sending query (non-interactive), then exiting.")
    else:
        print("Enter messages (type 'exit' to quit):")


def get_user_query() -> str:
    return input("\n> ")


DAC_PROGRESS_MARK = "[[DAC_PROGRESS]]"


def _suffix_overlap_with_marker(s: str, mark: str = DAC_PROGRESS_MARK) -> int:
    """Length of suffix of s that is a prefix of mark (keep in buffer; may be partial marker)."""
    max_k = min(len(s), len(mark) - 1)
    for k in range(max_k, 0, -1):
        if s[-k:] == mark[:k]:
            return k
    return 0


def _consume_json_object(s: str, start: int) -> int | None:
    """If s[start] is '{', return index after matching '}' at depth 0; None if incomplete."""
    if start >= len(s) or s[start] != "{":
        return None
    depth = 0
    in_str = False
    esc = False
    i = start
    while i < len(s):
        ch = s[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return i + 1
        i += 1
    return None


class DACProgressStreamFilter:
    """Strip [[DAC_PROGRESS]] {...} segments from streamed text; safe across chunk boundaries."""

    __slots__ = ("_buf", "_json_tail")

    def __init__(self) -> None:
        self._buf = ""
        self._json_tail: str | None = None

    def feed(self, chunk: str) -> str:
        if self._json_tail is not None:
            self._buf = self._json_tail + self._buf + chunk
            self._json_tail = None
        else:
            self._buf += chunk

        visible: list[str] = []
        mark = DAC_PROGRESS_MARK

        while True:
            idx = self._buf.find(mark)
            if idx < 0:
                hold = _suffix_overlap_with_marker(self._buf, mark)
                safe_len = len(self._buf) - hold
                if safe_len > 0:
                    visible.append(self._buf[:safe_len])
                    self._buf = self._buf[safe_len:]
                break

            if idx > 0:
                visible.append(self._buf[:idx])
            rest = self._buf[idx + len(mark) :].lstrip(" \t\n\r")
            self._buf = rest
            if not self._buf.startswith("{"):
                continue
            end = _consume_json_object(self._buf, 0)
            if end is None:
                self._json_tail = self._buf
                self._buf = ""
                break
            self._buf = self._buf[end:].lstrip(" \t\n\r")

        return "".join(visible)

    def finish(self) -> str:
        """Flush remainder: incomplete progress JSON is emitted as plain text."""
        parts: list[str] = []
        if self._json_tail is not None:
            parts.append(self._json_tail)
            self._json_tail = None
        if self._buf:
            parts.append(self._buf)
            self._buf = ""
        return "".join(parts)


async def stream_user_message(
    client: A2AClient,
    *,
    user_id: str,
    run_id: str,
    text: str,
) -> str:
    send_message_payload: dict[str, Any] = {
        "message": {
            "role": "user",
            "parts": [{"type": "text", "text": text}],
            "messageId": uuid4().hex,
        },
        "metadata": {
            "user_id": user_id,
            "run_id": run_id,
        },
    }

    visible_accumulated = ""
    try:
        streaming_request = SendStreamingMessageRequest(
            id=uuid4().hex,
            params=MessageSendParams(**send_message_payload),
        )

        filt = DACProgressStreamFilter()

        stream_response = client.send_message_streaming(streaming_request)
        async for chunk in stream_response:
            raw = get_response_text(chunk)
            if not raw:
                continue
            visible = filt.feed(raw)
            if visible:
                visible_accumulated += visible
                print(visible, end="", flush=True)
                await asyncio.sleep(0.1)

        tail = filt.finish()
        if tail:
            visible_accumulated += tail
            print(tail, end="", flush=True)

        print()
        return visible_accumulated

    except Exception as e:
        print(f"An error occurred: {e}")
        return ""


async def interact_with_server(
    client: A2AClient,
    *,
    user_id: str,
    run_id: str,
) -> None:
    while True:
        user_input = get_user_query()
        if user_input.lower() == "exit":
            print("bye!~")
            break

        await stream_user_message(
            client,
            user_id=user_id,
            run_id=run_id,
            text=user_input,
        )


def get_response_text(chunk: Any) -> str:
    data = chunk.model_dump(mode="json", exclude_none=True)
    if (result := data.get("result")) is not None:
        kind = result.get("kind")
        if kind == "artifact-update":
            artifact = result.get("artifact")
            parts = artifact.get("parts")
            if parts and len(parts) > 0 and isinstance(parts[0], dict):
                text = parts[0].get("text")
                return text if text else ""
    return ""


async def main_async(args: argparse.Namespace) -> None:
    query = (args.query or "").strip() or None
    print_welcome_message(
        args.user_id,
        args.run_id,
        args.url,
        initial_query=query,
    )

    async with httpx.AsyncClient() as httpx_client:
        resolver = A2ACardResolver(
            httpx_client=httpx_client,
            base_url=args.url,
        )

        try:
            _public_card = await resolver.get_agent_card()
        except Exception as e:
            print(
                f"Failed to fetch agent card from {args.url}: {e}",
                file=sys.stderr,
            )
            print(
                "Make sure the agent server is running and reachable. "
                "For local testing, use --url http://localhost:PORT (e.g. http://localhost:8000).",
                file=sys.stderr,
            )
            sys.exit(1)

        print("Successfully fetched public agent card:")
        print(_public_card.model_dump_json(indent=2, exclude_none=True))
        print("\nUsing PUBLIC agent card for client initialization (default).")

        client = A2AClient(httpx_client=httpx_client, agent_card=_public_card)
        print("A2AClient initialized.")

        if query is not None:
            await stream_user_message(
                client,
                user_id=args.user_id,
                run_id=args.run_id,
                text=query,
            )
        else:
            await interact_with_server(
                client,
                user_id=args.user_id,
                run_id=args.run_id,
            )


def main() -> None:
    args = parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
