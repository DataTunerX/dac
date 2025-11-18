from model_sdk import ModelManager
from langchain_core.messages import SystemMessage, HumanMessage

async def demonstrate_usage():

    manager = ModelManager()

    llm = manager.get_llm(
        provider="openai_compatible",
        api_key="sk-xxx",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model="qwen-plus",
        temperature=0.01,
        extra_body={
            "enable_thinking": False  # default to True
        },
    )

    print("=== sync call ===")
    sync_result = llm.invoke([HumanMessage(content="Hello")])
    print(sync_result.content)
    
    print("\n=== async call ===")
    async_result = await llm.ainvoke([HumanMessage(content="Hello async")])
    print(async_result.content)
    
    print("\n=== sync stream ===")
    for chunk in llm.stream([HumanMessage(content="Stream sync")]):
        print(chunk.content, end="", flush=True)
    
    print("\n\n=== async stream ===")
    async for chunk in llm.astream([HumanMessage(content="Stream async")]):
        print(chunk.content, end="", flush=True)


if __name__ == "__main__":
    import asyncio
    asyncio.run(demonstrate_usage())