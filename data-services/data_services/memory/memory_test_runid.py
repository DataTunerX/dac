import os
import sys
import time
from typing import List, Dict, Any
import logging
from model_sdk import ModelManager
# Add current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from memory import MemoryService

memory_service = MemoryService()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class MemoryServiceTester:
    def __init__(self):
        self.test_run_id = "test_run_001"
        self.test_memory_id = None
    
    def setup(self):
        """Initialize test environment"""
        logger.info("Setting up MemoryService for testing...")
        
        # Initialize model manager
        model_manager = ModelManager()
        
        # Initialize large language model
        llm_model = model_manager.get_llm(
            provider="openai_compatible",
            api_key=os.getenv('LLM_API_KEY', "sk-xxx"),
            base_url=os.getenv('LLM_BASE_URL', "https://dashscope.aliyuncs.com/compatible-mode/v1"),
            model=os.getenv('LLM_MODEL', "deepseek-v3"),
            temperature=float(os.getenv('LLM_TEMPERATURE', "0.01")),
            extra_body={
                "enable_thinking": False
            },
        )

        # Initialize vector model service
        embedder = model_manager.get_embedding(
            provider=os.getenv('EMBEDDING_PROVIDER', 'dashscope'),
            model=os.getenv('EMBEDDING_MODEL', 'text-embedding-v4'),
            dashscope_api_key=os.getenv('EMBEDDING_API_KEY', "sk-xxx")
        )

        # mem0 configuration
        memory_config = {
            "llm": {
                "provider": "langchain",
                "config": {
                    "model": llm_model
                }
            },
            "embedder": {
                "provider": "langchain",
                "config": {
                    "model": embedder,
                }
            },
            "vector_store": {
                "provider": "pgvector",
                "config": {
                    "user": os.getenv('PG_USER', 'postgres'),
                    "password": os.getenv('PG_PASSWORD', 'postgres'),
                    "host": os.getenv('PG_HOST', '192.168.xxx.xxx'),
                    "port": os.getenv('PG_PORT', '5433'),
                    "dbname": os.getenv('PG_DBNAME', 'postgres'),
                    "collection_name": os.getenv('PG_COLLECTION', 'memories'),
                    "embedding_model_dims": int(os.getenv('EMBEDDING_DIMS', '1024')),
                }
            }
        }

        # Initialize memory service
        memory_service.initialize(memory_config)
        logger.info("MemoryService initialized successfully")

    def test_add_memory(self):
        """Test adding memory"""
        logger.info("=====Testing add_memory...")
        
        messages = [
            {"role": "user", "content": "I'm planning to watch a movie tonight. Any recommendations?"},
            {"role": "assistant", "content": "How about a thriller movie? They can be quite engaging."},
            {"role": "user", "content": "I'm not a big fan of thriller movies but I love sci-fi movies."},
            {"role": "assistant", "content": "Got it! I'll avoid thriller recommendations and suggest sci-fi movies in the future."}
        ]
        
        metadata = {"category": "movies", "test": True}
        
        result = memory_service.add_memory(
            messages=messages,
            run_id=self.test_run_id,
            metadata=metadata
        )
        
        logger.info(f"Add memory result: {result}")
        
        # Modify here: properly handle return format
        if 'results' in result and len(result['results']) > 0:
            # If there are results, get the id of the first result
            self.test_memory_id = result['results'][0].get('id')
            logger.info(f"Memory created with ID: {self.test_memory_id}")
        elif 'id' in result:
            # Or directly has id field
            self.test_memory_id = result['id']
            logger.info(f"Memory created with ID: {self.test_memory_id}")
        else:
            # If neither, try to get the latest memory id from get_all_memories
            all_memories = memory_service.get_all_memories(run_id=self.test_run_id)
            if all_memories:
                self.test_memory_id = all_memories[-1]['id']  # Get the latest memory
                logger.info(f"Found memory ID from get_all: {self.test_memory_id}")
        
        return result
    
    def test_get_memory(self):
        """Test getting single memory"""
        if not self.test_memory_id:
            logger.warning("No memory ID available for get test")
            return None
        
        logger.info(f"=====Testing get_memory with ID: {self.test_memory_id}")
        
        result = memory_service.get_memory(self.test_memory_id)
        logger.info(f"Get memory result: {result}")
        
        return result
    
    def test_get_all_memories(self):
        """Test getting all memories"""
        logger.info(f"=====Testing get_all_memories for runid: {self.test_run_id}")
        
        result = memory_service.get_all_memories(run_id=self.test_run_id)
        logger.info(f"Found {len(result)} memories for runid {self.test_run_id}")
        
        for i, memory in enumerate(result):
            logger.info(f"Memory {i+1}: {memory}")
        
        return result
    
    def test_search_memories(self):
        """Test searching memories"""
        logger.info("=====Testing search_memories...")
        
        # Wait a bit to ensure data is indexed
        time.sleep(2)
        
        result = memory_service.search_memories(
            query="sci-fi movies",
            run_id=self.test_run_id,
            limit=3
        )
        
        logger.info(f"Search found {len(result)} results")
        for i, memory in enumerate(result):
            logger.info(f"Search result {i+1}: {memory}")
        
        return result
    
    def test_get_memory_history(self):
        """Test getting memory history"""
        if not self.test_memory_id:
            logger.warning("No memory ID available for history test")
            return None
        
        logger.info(f"=====Testing get_memory_history with ID: {self.test_memory_id}")
        
        result = memory_service.get_memory_history(self.test_memory_id)
        logger.info(f"Memory history has {len(result)} entries")
        
        return result

    def test_update_memory(self):
        """Test updating memory"""
        if not self.test_memory_id:
            logger.warning("No memory ID available for update test")
            return None
        
        logger.info(f"=====Testing update_memory with ID: {self.test_memory_id}")
        
        result = memory_service.update_memory(
            memory_id=self.test_memory_id,
            data="i like apple"
        )
        
        logger.info(f"Update memory result: {result}")
        return result

    def test_delete_memory(self):
        """Test deleting single memory"""
        if not self.test_memory_id:
            logger.warning("No memory ID available for delete test")
            return None
        
        logger.info(f"=====Testing delete_memory with ID: {self.test_memory_id}")
        
        result = memory_service.delete_memory(self.test_memory_id)
        logger.info(f"Delete memory result: {result}")
        
        # Reset memory_id
        self.test_memory_id = None
        
        return result
    
    def test_delete_all_memories(self):
        """Test deleting all memories"""
        logger.info(f"=====Testing delete_all_memories for runid: {self.test_run_id}")
        
        result = memory_service.delete_all_memories(run_id=self.test_run_id)
        logger.info(f"Delete all memories result: {result}")
        
        return result
    
    def run_all_tests(self):
        """Run all tests"""
        logger.info("Starting MemoryService tests...")
        
        try:
            self.setup()
            
            # Test adding memory
            add_result = self.test_add_memory()
            if not add_result:
                logger.error("Add memory test failed")
                return False
            
            # Wait a bit to ensure data is written
            time.sleep(1)
            
            # Test getting single memory
            get_result = self.test_get_memory()
            
            # Test getting all memories
            all_result = self.test_get_all_memories()
            
            # Test searching memories
            search_result = self.test_search_memories()
            
            # Test getting memory history
            history_result = self.test_get_memory_history()
            
            # Test deleting single memory
            delete_result = self.test_delete_memory()
            
            # Test deleting all memories
            delete_all_result = self.test_delete_all_memories()
            
            logger.info("All tests completed successfully!")
            return True
            
        except Exception as e:
            logger.error(f"Test failed with error: {str(e)}", exc_info=True)
            return False
    
    def run_basic_test(self):
        """Run basic functionality test (without deleting data)"""
        logger.info("Running basic functionality test...")
        
        try:
            self.setup()
            
            # Test adding memory
            add_result = self.test_add_memory()
            if not add_result:
                logger.error("Add memory test failed")
                return False
            
            time.sleep(1)
            
            # Test getting
            self.test_get_memory()
            self.test_get_all_memories()
            self.test_search_memories()
            
            logger.info("Basic functionality test completed!")
            return True
            
        except Exception as e:
            logger.error(f"Basic test failed with error: {str(e)}", exc_info=True)
            return False
        finally:
            # Clean up test data
            if self.test_memory_id:
                try:
                    memory_service.delete_memory(self.test_memory_id)
                    logger.info(f"Cleaned up test memory: {self.test_memory_id}")
                except Exception as e:
                    logger.warning(f"Failed to clean up memory: {e}")

def main():
    """Main function"""
    tester = MemoryServiceTester()
    
    # Select test mode
    test_mode = input("Select test mode (1=full test, 2=basic test): ").strip()
    
    if test_mode == "1":
        success = tester.run_all_tests()
    else:
        success = tester.run_basic_test()
    
    if success:
        logger.info("✅ All tests passed!")
        return 0
    else:
        logger.error("❌ Tests failed!")
        return 1

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
