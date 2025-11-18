# from model_sdk import ModelManager
# from langchain_core.messages import SystemMessage, HumanMessage

# async def demonstrate_usage():

#     manager = ModelManager()

#     # llm = manager.get_llm(
#     #     provider="openai_compatible",
#     #     api_key="sk-nhE1GA5wCCtTVh76yB7LmW2KeJaXVmEWORv4m1uhmRk",
#     #     base_url="https://chat.d.run/v1",
#     #     model="public/qwen3-235b-a22b-fp8",
#     #     temperature=0.7,
#     #     extra_body={
#     #         "enable_thinking": False  # default to True
#     #     },
#     # )
    

#     # # 同步调用
#     # print("=== 同步调用 ===")
#     # sync_result = llm.invoke([HumanMessage(content="Hello")])
#     # print(sync_result.content)
    
#     # # 异步调用
#     # print("\n=== 异步调用 ===")
#     # async_result = await llm.ainvoke([HumanMessage(content="Hello async")])
#     # print(async_result.content)
    
#     # # 同步流式
#     # print("\n=== 同步流式 ===")
#     # for chunk in llm.stream([HumanMessage(content="Stream sync")]):
#     #     print(chunk.content, end="", flush=True)
    
#     # # 异步流式
#     # print("\n\n=== 异步流式 ===")
#     # async for chunk in llm.astream([HumanMessage(content="Stream async")]):
#     #     print(chunk.content, end="", flush=True)
    

    
#     # Embedding调用测试
#     embedding = manager.get_embedding(
#         provider = "openai_compatible",
#         model = "bge-m3",
#         base_url = "http://10.17.0.41:30636/v1",
#         api_key = "asd"
#     )
    
#     # print("\n\n=== 同步Embedding ===")
#     print(embedding.embed_query("Hello"))
    
#     # # print("\n=== 异步Embedding ===")
#     # print(await embedding.aembed_query("Hello async"))


#     # # 获取rerank实例
#     # rerank = manager.get_rerank(
#     #     provider="openai_compatible",
#     #     model_name="bge-reranker-v2-m3",
#     #     model_config={
#     #         "api_key": "asd",
#     #         "base_url": "http://10.17.0.41:31322/v1"
#     #     }
#     # )
    
#     # query = "What is the capital of France?"
#     # documents = [
#     #     "Paris is the capital of France",
#     #     "London is the capital of UK",
#     #     "Berlin is the capital of Germany"
#     # ]
    
#     # # 同步调用
#     # print("=== 同步Rerank ===")
#     # result = rerank.invoke(
#     #     query=query,
#     #     docs=documents,
#     #     top_n=2,
#     #     score_threshold=0.5
#     # )
#     # for doc in result.docs:
#     #     print(f"Score: {doc.score:.2f} | Doc: {doc.text}")
    
#     # # 异步调用
#     # print("\n=== 异步Rerank ===")
#     # result = await rerank.ainvoke(
#     #     query=query,
#     #     docs=documents,
#     #     top_n=2
#     # )
#     # for doc in result.docs:
#     #     print(f"Score: {doc.score:.2f} | Doc: {doc.text}")

# if __name__ == "__main__":
#     import asyncio
#     asyncio.run(demonstrate_usage())


from model_sdk import ModelManager
from langchain_core.messages import SystemMessage, HumanMessage

async def demonstrate_usage():

    manager = ModelManager()
    
    # Embedding调用测试
    embedding = manager.get_embedding(
        provider='dashscope',
        model='text-embedding-v4',
        # base_url="https://dashscope.aliyuncs.com/compatible-mode/v1", 
        dashscope_api_key="sk-xxx"
    )
    
    # print("\n\n=== 同步Embedding ===")
    print(embedding.embed_query("Hello"))
    
    # print("\n=== 异步Embedding ===")
    print(await embedding.aembed_query("Hello async"))

if __name__ == "__main__":
    import asyncio
    asyncio.run(demonstrate_usage())
