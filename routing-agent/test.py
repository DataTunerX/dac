import httpx
import asyncio
from a2a.client import A2ACardResolver, A2AClient
from typing import Any
from uuid import uuid4
from a2a.types import (
    MessageSendParams,
    SendStreamingMessageRequest,
    TaskArtifactUpdateEvent,
)
import sys

def print_welcome_message() -> None:
    print("Welcome to the generic A2A client!")
    print("Please enter your query (type 'exit' to quit):")

def get_user_query() -> str:
    return input("\n> ")

async def interact_with_server(client: A2AClient) -> None:
    while True:
        user_input = get_user_query()
        if user_input.lower() == 'exit':
            print("bye!~")
            break

        send_message_payload: dict[str, Any] = {
            'message': {
                'role': 'user',
                'parts': [
                    {'type': 'text', 'text': user_input}
                ],
                'messageId': uuid4().hex,
            },
            'metadata': {
                'user_id': 'user1106',
                'run_id': 'run1106',
            },
        }

        try:
            streaming_request = SendStreamingMessageRequest(
                id=uuid4().hex,
                params=MessageSendParams(**send_message_payload)
            )
            
            stream_response = client.send_message_streaming(streaming_request)
            async for chunk in stream_response:
                result = get_response_text(chunk)
                if result:
                    # 流式连续输出
                    print(result, end="", flush=True)
                    await asyncio.sleep(0.1)
            
            # 在响应结束后打印换行
            print()
            
        except Exception as e:
            print(f"An error occurred: {e}")

def get_response_text(chunk) -> str:
    data = chunk.model_dump(mode='json', exclude_none=True)
    if (result := data.get('result')) is not None:
        kind = result.get('kind')
        if kind == 'artifact-update':
            artifact = result.get('artifact')
            parts = artifact.get('parts')
            if parts and len(parts) > 0 and isinstance(parts[0], dict):
                text = parts[0].get('text')
                return text if text else ""
    return ""

async def main() -> None:
    print_welcome_message()

    base_url = 'http://192.168.xxx.xxx:20002'

    async with httpx.AsyncClient() as httpx_client:
        resolver = A2ACardResolver(
            httpx_client=httpx_client,
            base_url=base_url,
        )
        final_agent_card_to_use = None

        _public_card = await resolver.get_agent_card()
        print('Successfully fetched public agent card:')
        print(_public_card.model_dump_json(indent=2, exclude_none=True))
        final_agent_card_to_use = _public_card
        print('\nUsing PUBLIC agent card for client initialization (default).')

        client = A2AClient(httpx_client=httpx_client, agent_card=final_agent_card_to_use)
        print('A2AClient initialized.')

        await interact_with_server(client)


if __name__ == '__main__':
    asyncio.run(main())
