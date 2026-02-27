import os
import sys
import logging
import asyncio
from typing import List, Dict, Any

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
sys.path.insert(0, project_root)

from data_services.knowledge_pyramid.knowledge_pyramid import KnowledgePyramidService
from data_services.api.base import DocumentModel, SearchType

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

testdata = """
'`balance_sheet` 表记录了各分行在特定日期的财务状况，包括总资产、客户贷款、同业资产、其他资产、总负债、客户存款、同业负债、其他负债、客户总数、个人客户数、企业客户数、同业客户数及员工总数。`deposit_data` 表详细列出了各分行在特定日期的存款情况，涵盖客户存款总额、企业存款总额、企业活期存款、企业定期存款、零售存款总额、零售活期存款及零售定期存款。`loan_data` 表提供了各分行在特定日期的贷款详情，包括客户贷款总额、实质性贷款总额、企业贷款总额、普惠小微企业贷款、零售贷款总额、信用卡贷款、中型企业贷款、大型企业贷款、中型及小型企业贷款、大型企业贷款、总贴现额、直接贴现及转贴现。`retail_loan_detail` 表则进一步细分了零售贷款的具体构成，如零售贷款总额、抵押贷款总额、一手房抵押贷款、二手房抵押贷款及消费贷款总额。 \n\n \n## Table: `balance_sheet`\n\n| Column | Type | Nullable | Key | Comment |\n|--------|------|----------|-----|---------|\n| `data_date` | `date` | NO | PRI |  |\n| `branch_id` | `varchar(4)` | NO | PRI |  |\n| `branch_name` | `varchar(50)` | NO | PRI |  |\n| `total_assets` | `decimal(18,0)` | YES |  |  |\n| `customer_loans` | `decimal(18,0)` | YES |  |  |\n| `interbank_assets` | `decimal(18,0)` | YES |  |  |\n| `other_assets` | `decimal(18,0)` | YES |  |  |\n| `total_liabilities` | `decimal(18,0)` | YES |  |  |\n| `customer_deposits` | `decimal(18,0)` | YES |  |  |\n| `interbank_liabilities` | `decimal(18,0)` | YES |  |  |\n| `other_liabilities` | `decimal(18,0)` | YES |  |  |\n| `total_customers` | `int` | YES |  |  |\n| `individual_customers` | `int` | YES |  |  |\n| `corporate_customers` | `int` | YES |  |  |\n| `interbank_customers` | `int` | YES |  |  |\n| `total_employees` | `int` | YES |  |  |\n\n## Table: `deposit_data`\n\n| Column | Type | Nullable | Key | Comment |\n|--------|------|----------|-----|---------|\n| `data_date` | `date` | NO | PRI | YYYY/MM/DD |\n| `branch_id` | `varchar(4)` | NO | PRI | 4 |\n| `branch_name` | `varchar(50)` | NO | PRI |  |\n| `customer_deposit_total` | `decimal(18,0)` | YES |  | + |\n| `corporate_deposit_total` | `decimal(18,0)` | YES |  |  |\n| `corporate_current_deposit` | `decimal(18,0)` | YES |  |  |\n| `corporate_term_deposit` | `decimal(18,0)` | YES |  |  |\n| `retail_deposit_total` | `decimal(18,0)` | YES |  |  |\n| `retail_current_deposit` | `decimal(18,0)` | YES |  |  |\n| `retail_term_deposit` | `decimal(18,0)` | YES |  |  |\n\n## Table: `loan_data`\n\n| Column | Type | Nullable | Key | Comment |\n|--------|------|----------|-----|---------|\n| `data_date` | `date` | NO | PRI | YYYY/MM/DD |\n| `branch_id` | `varchar(4)` | NO | PRI | 4 |\n| `branch_name` | `varchar(50)` | NO | PRI |  |\n| `total_customer_loan` | `decimal(18,0)` | YES |  |  |\n| `substantive_loan_total` | `decimal(18,0)` | YES |  |  |\n| `corporate_loan_total` | `decimal(18,0)` | YES |  |  |\n| `inclusive_sme_loan` | `decimal(18,0)` | YES |  |  |\n| `retail_loan_total` | `decimal(18,0)` | YES |  |  |\n| `credit_card_loan` | `decimal(18,0)` | YES |  |  |\n| `medium_small_loan` | `decimal(18,0)` | YES |  |  |\n| `large_loan` | `decimal(18,0)` | YES |  |  |\n| `medium_small_corporate_loan` | `decimal(18,0)` | YES |  |  |\n| `large_corporate_loan` | `decimal(18,0)` | YES |  |  |\n| `total_discount` | `decimal(18,0)` | YES |  | + |\n| `direct_discount` | `decimal(18,0)` | YES |  |  |\n| `transfer_discount` | `decimal(18,0)` | YES |  |  |\n\n## Table: `retail_loan_detail`\n\n| Column | Type | Nullable | Key | Comment |\n|--------|------|----------|-----|---------|\n| `data_date` | `date` | NO | PRI | YYYY/MM/DD |\n| `branch_id` | `varchar(4)` | NO | PRI | 4 |\n| `branch_name` | `varchar(50)` | NO | PRI |  |\n| `retail_loan_total` | `decimal(18,2)` | YES |  |  |\n| `mortgage_total` | `decimal(18,2)` | YES |  |  |\n| `first_hand_mortgage` | `decimal(18,2)` | YES |  |  |\n| `second_hand_mortgage` | `decimal(18,2)` | YES |  |  |\n| `consumer_loan_total` | `decimal(18,2)` | YES |  |  | \n\n sample data:\n[\n  {\n    "table_name": "balance_sheet",\n    "sample_data": {\n      "data_date": "2023-11-30",\n      "branch_id": "9200",\n      "branch_name": "",\n      "total_assets": "113962000000",\n      "customer_loans": "51957000000",\n      "interbank_assets": "52900000000",\n      "other_assets": "9105000000",\n      "total_liabilities": "91641800000",\n      "customer_deposits": "46901000000",\n      "interbank_liabilities": "42800000000",\n      "other_liabilities": "1940800000",\n      "total_customers": 781347,\n      "individual_customers": 763683,\n      "corporate_customers": 17376,\n      "interbank_customers": 288,\n      "total_employees": 12378\n    }\n  },\n  {\n    "table_name": "deposit_data",\n    "sample_data": {\n      "data_date": "2023-11-30",\n      "branch_id": "9200",\n      "branch_name": "",\n      "customer_deposit_total": "46901000000",\n      "corporate_deposit_total": "22536300000",\n      "corporate_current_deposit": "15850250000",\n      "corporate_term_deposit": "6686050000",\n      "retail_deposit_total": "24364700000",\n      "retail_current_deposit": "16237920000",\n      "retail_term_deposit": "8126780000"\n    }\n  },\n  {\n    "table_name": "loan_data",\n    "sample_data": {\n      "data_date": "2023-11-30",\n      "branch_id": "9200",\n      "branch_name": "",\n      "total_customer_loan": "51957000000",\n      "substantive_loan_total": "41566850000",\n      "corporate_loan_total": "24108821500",\n      "inclusive_sme_loan": "10319317040",\n      "retail_loan_total": "7138711460",\n      "credit_card_loan": "2526750000",\n      "medium_small_loan": "17458028500",\n      "large_loan": "24108821500",\n      "medium_small_corporate_loan": "13416839645",\n      "large_corporate_loan": "10691981855",\n      "total_discount": "7863400000",\n      "direct_discount": "6028631000",\n      "transfer_discount": "1834769000"\n    }\n  },\n  {\n    "table_name": "retail_loan_detail",\n    "sample_data": {\n      "data_date": "2023-11-30",\n      "branch_id": "9200",\n      "branch_name": "",\n      "retail_loan_total": "7138711460.00",\n      "mortgage_total": "4446734585.20",\n      "first_hand_mortgage": "2223367292.60",\n      "second_hand_mortgage": "2223367292.60",\n      "consumer_loan_total": "2691976874.80"\n    }\n  }\n'
"""

class KnowledgePyramidTester:
    def __init__(self):
        self.test_collection = "test_knowledge_pyramid8"
        self.knowledge_service = KnowledgePyramidService()
        self.added_document_ids = []

    def setup_environment(self):
        """Set up test environment variables"""
        os.environ.update({
            # Telemetry configuration
            'EC_TELEMETRY': 'False',
            'MEM0_TELEMETRY': 'False',
            
            # Embedding model configuration
            'EMBEDDING_PROVIDER': 'dashscope',
            'EMBEDDING_API_KEY': 'sk-xxx',
            'EMBEDDING_MODEL': 'text-embedding-v4',
            
            # LLM configuration
            'LLM_API_KEY': 'sk-xxx',
            'LLM_BASE_URL': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
            'LLM_MODEL': 'deepseek-v3',
            'LLM_TEMPERATURE': '0.01',
            
            # Memory vector database configuration
            'MEMORY_PGVECTOR_HOST': '192.168.3.238',
            'MEMORY_PGVECTOR_PORT': '5433',
            'MEMORY_PGVECTOR_USER': 'postgres',
            'MEMORY_PGVECTOR_PASSWORD': 'postgres',
            'MEMORY_PGVECTOR_MIN_CONNECTION': '1',
            'MEMORY_PGVECTOR_MAX_CONNECTION': '10',
            'MEMORY_DBNAME': 'agent_memory',
            'MEMORY_COLLECTION': 'memories',
            'MEMORY_EMBEDDING_DIMS': '1024',
            
            # General vector database configuration (maintain backward compatibility)
            'PGVECTOR_HOST': '192.168.3.238',
            'PGVECTOR_PORT': '5433',
            'PGVECTOR_USER': 'postgres',
            'PGVECTOR_PASSWORD': 'postgres',
            'PGVECTOR_DATABASE': 'knowledge_vector',
            'PGVECTOR_MIN_CONNECTION': '1',
            'PGVECTOR_MAX_CONNECTION': '10',
        })
        logger.info("Environment variables set")

    async def initialize_service(self):
        """Initialize knowledge pyramid service"""
        try:
            logger.info("Initializing Knowledge Pyramid Service...")
            await self.knowledge_service.initialize()
            logger.info("Knowledge Pyramid Service initialized successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize service: {str(e)}")
            return False

    def create_test_documents(self) -> List[DocumentModel]:
        """Create test documents"""
        return [
            DocumentModel(
                page_content="I'm not a big fan of thriller movies but I love sci-fi movies.",
                metadata={"category": "technology", "source": "wikipedia", "language": "english"}
            ),
            DocumentModel(
                page_content="机器学习是人工智能的一个子领域，它使计算机能够在没有明确编程的情况下学习和改进。",
                metadata={"category": "technology", "source": "academic", "language": "chinese"}
            )
        ]

    async def test_add_documents(self):
        """Test adding documents to knowledge pyramid"""
        logger.info("===== Testing add_documents_with_knowledge_pyramid =====")
        
        test_documents = self.create_test_documents()
        
        try:
            result = await self.knowledge_service.add_documents_with_knowledge_pyramid1(
                collection_name=self.test_collection,
                documents=test_documents
            )
            
            logger.info(f"Add documents result: {result}")
            
            if result["status"] == "success":
                # Extract IDs based on actual return structure
                vector_results = result.get("vector_results", [])
                
                # Save document IDs (list of strings)
                if isinstance(vector_results, list) and all(isinstance(id, str) for id in vector_results):
                    self.added_document_ids = vector_results
                    logger.info(f"Document IDs: {self.added_document_ids}")
                else:
                    logger.warning(f"Unexpected vector_results format: {vector_results}")
                logger.info(f"Successfully added {len(test_documents)} documents")
                logger.info(f"Got {len(self.added_document_ids)} document IDs")
                return True
            else:
                logger.error(f"Failed to add documents: {result.get('message', 'Unknown error')}")
                return False
                
        except Exception as e:
            logger.error(f"Error in add_documents test: {str(e)}")
            return False

    async def test_search_documents(self):
        """Test searching documents"""
        logger.info("===== Testing search_documents_with_knowledge_pyramid =====")
        
        try:
            result = await self.knowledge_service.search_documents_with_knowledge_pyramid(
                query="机器学习",
                collection_name=self.test_collection,
                search_type=SearchType.VECTOR,
                limit=10
            )
            
            logger.info(f"Search result status: {result['status']}")
            
            if result["status"] == "success":
                vector_results = result.get("vector_result", [])
                logger.info(f"Found {len(vector_results)} vector results")
                
                # Display some search result details
                if vector_results:
                    for i, doc in enumerate(vector_results[:2]):  # Only show first 2
                        logger.info(f"Vector result {i+1}: {doc.get('content', '')[:100]}...")
                        logger.info(f"  Score: {doc.get('score', 0)}, Metadata: {doc.get('metadata', {})}")
                
                return True
            else:
                logger.error(f"Search failed: {result.get('message', 'Unknown error')}")
                return False
                    
        except Exception as e:
            logger.error(f"Error in search test: {str(e)}")
            return False

    async def test_find_metadata_values_in_collections(self):
        """Test searching documents"""
        logger.info("===== Testing search_documents_with_knowledge_pyramid =====")
        
        try:
            collection_names=["embedding_dac_dd_d07", "embedding_dac_dd_d08"]

            result = await self.knowledge_service.find_metadata_values_in_collections(collection_names=collection_names, metadata_key="source")
            
            logger.info(f"Search result status: {result}")
                    
        except Exception as e:
            logger.error(f"Error in search test: {str(e)}")
            return False

    async def test_delete_documents_by_ids(self):
        """Test deleting documents and memories by IDs"""
        logger.info("===== Testing delete_documents_by_ids =====")
        
        if not self.added_document_ids:
            logger.error("No document IDs available for deletion test")
            return False
        
        try:
            # Use actual obtained IDs for testing
            logger.info(f"Deleting document IDs: {self.added_document_ids[:1]}")  # Only delete first one
            
            result = await self.knowledge_service.delete_documents_by_ids(
                collection_name=self.test_collection,
                documents=self.added_document_ids[:1]  # Only delete first document
            )
            
            logger.info(f"Delete by IDs result: {result}")
            
            if result["status"] == "success":
                logger.info("✅ Delete by IDs operation completed successfully")
                
                # Verify deletion effect
                await asyncio.sleep(1)
                logger.info("Verifying deletion by searching again...")
                
                search_result = await self.knowledge_service.search_documents_with_knowledge_pyramid(
                    query="机器学习",
                    collection_name=self.test_collection,
                    search_type=SearchType.VECTOR,
                    limit=10
                )
                
                logger.info(f"Remaining after deletion: {search_result}")
                
                return True
            else:
                logger.error(f"Failed to delete by IDs: {result.get('message', 'Unknown error')}")
                return False
                
        except Exception as e:
            logger.error(f"Error in delete by IDs test: {str(e)}")
            return False

    async def test_delete_all_documents(self):
        """Test deleting all documents and memories"""
        logger.info("===== Testing delete_all_documents_by_collection_name =====")
        
        # First ensure there is some data
        if not self.added_document_ids:
            logger.info("Adding test documents first...")
            if not await self.test_add_documents():
                return False
            await asyncio.sleep(2)
        
        try:
            result = await self.knowledge_service.delete_all_documents_by_collection_name(
                collection_name=self.test_collection
            )
            
            logger.info(f"Delete all result: {result}")
            
            if result["status"] == "success":
                logger.info(f"✅ Successfully deletion of all documents from collection: {self.test_collection}")
                return True
            else:
                logger.error(f"Failed to delete all: {result.get('message', 'Unknown error')}")
                return False
                
        except Exception as e:
            logger.error(f"Error in delete all test: {str(e)}")
            return False

    async def run_all_tests(self):
        """Run all tests"""
        logger.info("Starting Knowledge Pyramid Service tests...")
        
        try:
            self.setup_environment()
            
            if not await self.initialize_service():
                return False
            
            # # Test 1: Adding documents
            # logger.info("\n" + "="*50)
            # logger.info("TEST 1: Adding Documents")
            # logger.info("="*50)
            # if not await self.test_add_documents():
            #     return False
            
            # await asyncio.sleep(2)
            
            # # Test 2: Searching documents
            # logger.info("\n" + "="*50)
            # logger.info("TEST 2: Searching Documents")
            # logger.info("="*50)
            # if not await self.test_search_documents():
            #     return False
            
            # await asyncio.sleep(1)


            # # Test 3: Searching documents
            logger.info("\n" + "="*50)
            logger.info("TEST 3: Searching metadata Documents")
            logger.info("="*50)
            if not await self.test_find_metadata_values_in_collections():
                return False
            
            await asyncio.sleep(1)
            
            # # Test 4: Deleting by IDs
            # logger.info("\n" + "="*50)
            # logger.info("TEST 3: Deleting by IDs")
            # logger.info("="*50)
            # if not await self.test_delete_documents_by_ids():
            #     return False
            
            # await asyncio.sleep(1)
            
            # # Re-add documents for full deletion test
            # logger.info("\n" + "="*50)
            # logger.info("Re-adding documents for full deletion test")
            # logger.info("="*50)
            # if not await self.test_add_documents():
            #     return False
            
            # await asyncio.sleep(2)
            
            # # Test 5: Deleting all
            # logger.info("\n" + "="*50)
            # logger.info("TEST 4: Deleting All Documents")
            # logger.info("="*50)
            # if not await self.test_delete_all_documents():
            #     return False
            
            logger.info("\n" + "="*50)
            logger.info("✅ All tests passed successfully!")
            logger.info("="*50)
            return True
            
        except Exception as e:
            logger.error(f"Test failed with error: {str(e)}")
            return False

async def main():
    """Main function"""
    tester = KnowledgePyramidTester()
    success = await tester.run_all_tests()
    
    if success:
        logger.info("🎉 All tests passed!")
        return 0
    else:
        logger.error("❌ Tests failed!")
        return 1

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
