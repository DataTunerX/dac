from model_sdk import ModelManager
from langchain_core.messages import SystemMessage, HumanMessage

async def demonstrate_usage():

    manager = ModelManager()
    
    # Embedding调用测试
    embedding = manager.get_embedding(
        provider='azure',
        model='text-embedding-ada-002',
        azure_endpoint="https://japan-east-pro.openai.azure.com", 
        api_key="xxx",
        deployment="text-embedding-ada-002",
        api_version="2023-05-15"
        
    )
    
    # print("\n\n=== 同步Embedding ===")
    print(embedding.embed_query("Hello"))
    
    # print("\n=== 异步Embedding ===")
    print(await embedding.aembed_query("Hello async"))

if __name__ == "__main__":
    import asyncio
    asyncio.run(demonstrate_usage())
