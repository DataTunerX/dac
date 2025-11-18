import os
from typing import List
from pydantic import BaseModel
from vector_sdk import Vector
from vector_sdk import Document
from vector_sdk import CacheEmbedding
from model_sdk import ModelManager
import uuid
from langchain_openai import AzureOpenAIEmbeddings


def main():

    model_manager = ModelManager()

    # model_instance = model_manager.get_embedding(
    #     provider = "openai_compatible",
    #     model = "bge-m3",
    #     base_url = "http://10.xxx.xxx.xxx:xxx/v1",
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

    os.environ['PGVECTOR_PORT'] = '5433'  # Note: must be string
    os.environ['PGVECTOR_USER'] = 'postgres'
    os.environ['PGVECTOR_PASSWORD'] = 'postgres'  # Change to your actual password
    os.environ['PGVECTOR_DATABASE'] = 'knowledge_vector'
    os.environ['PGVECTOR_MIN_CONNECTION'] = '1'
    os.environ['PGVECTOR_MAX_CONNECTION'] = '5'

    # Initialize the vector store
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
    
    # Test creating the collection and adding documents
    # print("Creating collection...")
    # vector.create(texts=documents)

    # Test creating the collection and adding documents
    print("Exist collection...")
    exist=vector.collection_exists()
    print(f"Exist collection {exist}")


    # print("Adding documents...")
    # doc_ids = vector.add_texts(documents=documents)
    # print(f"add_texts , doc_ids = {doc_ids}...")
    
    # # Test searching by vector
    # print("\nSearching by vector similarity...")
    # query = "programming languages"
    # results = vector.search_by_vector(query, top_k=2)
    # for i, doc in enumerate(results):
    #     print(f"Result {i+1}:")
    #     print(f"Content: {doc.page_content}")
    #     print(f"Metadata: {doc.metadata}")
    #     print(f"Score: {doc.metadata['score']:.4f}")
    #     print()
    
    # # Test searching by full text
    # print("\nSearching by full text...")
    # query = "fox jumps"
    # results = vector.search_by_full_text(query, top_k=1)
    # for i, doc in enumerate(results):
    #     print(f"Result {i+1}:")
    #     print(f"Content: {doc.page_content}")
    #     print(f"Metadata: {doc.metadata}")
    #     print(f"Score: {doc.metadata['score']:.4f}")
    #     print()
    
    # # Test checking if text exists
    # print("\nChecking if documents exist...")
    # print(f"Document 'doc1' exists: {vector.text_exists('doc1')}")
    # print(f"Document 'nonexistent' exists: {vector.text_exists('nonexistent')}")
    
    # # Test deleting by ID
    # print("\nDeleting document 'doc2'...")
    # vector.delete_by_ids(["doc2"])
    # print(f"Document 'doc2' exists after deletion: {vector.text_exists('doc2')}")
    
    # Test deleting by metadata field
    # print("\nDeleting documents by author 'Alan Turing'...")
    # vector.delete_by_metadata_field("author", "Alan Turing")
    # print(f"Document 'doc3' exists after deletion: {vector.text_exists('doc3')}")
    
    # Clean up - delete the entire collection
    # print("\nCleaning up - deleting collection...")
    # vector.delete()

if __name__ == "__main__":
    main()