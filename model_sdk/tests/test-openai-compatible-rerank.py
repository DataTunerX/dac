import os
from dotenv import load_dotenv
from model_sdk import ModelManager

load_dotenv()

async def demonstrate_rerank():
    manager = ModelManager()
    
    rerank = manager.get_rerank(
        provider="openai_compatible",
        model_name="bge-reranker-v2-m3",
        model_config={
            "api_key": "asd",
            "base_url": "http://10.xxx.xxx.xxx:xxx/v1"
        }
    )
    
    query = "What is the capital of France?"
    documents = [
        "Paris is the capital of France",
        "London is the capital of UK",
        "Berlin is the capital of Germany"
    ]
    
    print("=== sync Rerank ===")
    result = rerank.invoke(
        query=query,
        docs=documents,
        top_n=2,
        score_threshold=0.5
    )
    for doc in result.docs:
        print(f"Score: {doc.score:.2f} | Doc: {doc.text}")
    
    print("\n=== async Rerank ===")
    result = await rerank.ainvoke(
        query=query,
        docs=documents,
        top_n=2
    )
    for doc in result.docs:
        print(f"Score: {doc.score:.2f} | Doc: {doc.text}")

if __name__ == "__main__":
    import asyncio
    asyncio.run(demonstrate_rerank())