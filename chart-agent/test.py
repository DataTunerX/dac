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

# 程序中要发送的内容，直接修改此变量即可测试不同输入
content = """
根据提供的销售数据分析，**华为Watch GT4** 属于最畅销的商品之一。

**具体分析如下：**
*   **销售数量**：华为Watch GT4的总销售数量为 **2件**。
*   **排名情况**：在所有产品中，其销量与“佳明Forerunner265”和“儿童冬季外套”并列 **第二**。
*   **对比说明**：销量最高的产品是“森海塞尔MOMENTUM真无线”（4件）。因此，基于销售数量，华为Watch GT4是排名前列的最畅销产品之一。
"""

content1 = """
根据提供的销售数据分析，**华为Watch GT4** 属于最畅销的商品之一。

"""

async def send_content_and_print(client: A2AClient) -> None:
    send_message_payload: dict[str, Any] = {
        'message': {
            'role': 'user',
            'parts': [
                {'type': 'text', 'text': content}
            ],
            'messageId': uuid4().hex,
        },
        'metadata': {
            'user_id': 'user123456',
            'agent_id': 'agent123456',
            'run_id': 'run123456',
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
                print(result, end="", flush=True)
                await asyncio.sleep(0.1)

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
    base_url = 'http://192.168.3.7:20006'

    print(f"发送内容 (content): {content!r}\n")

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
        print('A2AClient initialized.\n')

        await send_content_and_print(client)


if __name__ == '__main__':
    asyncio.run(main())