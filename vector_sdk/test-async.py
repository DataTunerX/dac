import asyncio
import uuid
import os
from typing import List
from pydantic import BaseModel
from vector_sdk import Vector
from vector_sdk import Document
from vector_sdk import CacheEmbedding
from model_sdk import ModelManager
from langchain_openai import AzureOpenAIEmbeddings


async def async_main():

    model_manager = ModelManager()

    # model_instance = model_manager.get_embedding(
    #     provider = "openai_compatible",
    #     model = "bge-m3",
    #     base_url = "http://xxx.xxx.xxx.xxx:xxx/v1",
    #     api_key = "asd"
    # )

    # model_instance = model_manager.get_embedding(
    #     provider='azure',
    #     model='text-embedding-ada-002',
    #     azure_endpoint="https://japan-east-pro.openai.azure.com", 
    #     api_key="xxx",
    #     deployment="text-embedding-ada-002",
    #     api_version="2023-05-15"
        
    # )

    model_instance = model_manager.get_embedding(
        provider='dashscope',
        model='text-embedding-v4',
        dashscope_api_key="sk-xxx"
    )

    embedding = CacheEmbedding(model_instance)

    os.environ['PGVECTOR_HOST'] = '192.168.xxx.xxx'
    os.environ['PGVECTOR_PORT'] = '5433'
    os.environ['PGVECTOR_USER'] = 'postgres'
    os.environ['PGVECTOR_PASSWORD'] = 'postgres'
    os.environ['PGVECTOR_DATABASE'] = 'knowledge_vector'
    os.environ['PGVECTOR_MIN_CONNECTION'] = '1'
    os.environ['PGVECTOR_MAX_CONNECTION'] = '5'

    collection_name = "test_knowledge"
    vector = Vector(collection_name=collection_name, embedding=embedding)
    
    # Create some test documents
    documents = [
        Document(
            page_content="The quick brown fox jumps over the lazy dog",
            metadata={"doc_id": str(uuid.uuid4()), "author": "John Doe"}
        ),
        Document(
            page_content="Lorem ipsum dolor sit amet, consectetur adipiscing elit",
            metadata={"doc_id": str(uuid.uuid4()), "author": "Jane Smith"}
        ),
        Document(
            page_content="Python is a popular programming language",
            metadata={"doc_id": str(uuid.uuid4()), "author": "Alan Turing"}
        )
    ]
    
    # print("Creating collection asynchronously...")
    # await vector.acreate(texts=documents)

    print("Exist collection...")
    exist = await vector.acollection_exists()
    print(f"Exist collection {exist}")

    # print("Adding documents asynchronously...")
    # doc_ids = await vector.aadd_texts(documents=documents)
    # print(f"\naadd_texts , doc_ids = {doc_ids}...")

    
    # print("\nSearching by vector similarity asynchronously...")
    # query = "programming languages"
    # results = await vector.asearch_by_vector(query, top_k=2)
    # for i, doc in enumerate(results):
    #     print(f"Result {i+1}:")
    #     print(f"Content: {doc.page_content}")
    #     print(f"Metadata: {doc.metadata}")
    #     print(f"Score: {doc.metadata['score']:.4f}")
    #     print()


    # Test searching by full text
    print("\nSearching by full text...")
    query = "fox jumps"
    results = await vector.asearch_by_full_text(query, top_k=1)
    for i, doc in enumerate(results):
        print(f"Result {i+1}:")
        print(f"Content: {doc.page_content}")
        print(f"Metadata: {doc.metadata}")
        print(f"Score: {doc.metadata['score']:.4f}")
        print()
    
    # print("\nCleaning up - deleting collection asynchronously...")
    # await vector.adelete()


if __name__ == "__main__":
    
    # 运行异步测试
    asyncio.run(async_main())