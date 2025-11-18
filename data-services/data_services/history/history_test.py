import os
import sys
import asyncio
import random
import string
from datetime import datetime
from typing import List, Dict, Any
import uuid
import json
from faker import Faker  # Used for generating test data

# Add project root directory to Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
sys.path.insert(0, project_root)
from data_services.api.base import HistoryRecord
from data_services.history.history import AsyncHistoryService


class HistoryServiceTester:
    def __init__(self):
        self.service = AsyncHistoryService(pool_size=10)
        self.fake = Faker()
        self.test_history_records = []  # Store records created for testing
    
    def generate_conversation(self, num_exchanges: int = 3) -> str:
        """Generate conversation records, including dialogues between human and assistant"""
        conversation = {
            "exchanges": []
        }
        
        for i in range(num_exchanges):
            exchange = {
                "human": self.fake.sentence(),
                "assistant": self.fake.text(max_nb_chars=200),
                "timestamp": datetime.now().isoformat()
            }
            conversation["exchanges"].append(exchange)
        
        return json.dumps(conversation, ensure_ascii=False)
    
    def generate_test_history_record(self) -> HistoryRecord:
        """Generate test history record data"""
        return HistoryRecord(
            hid=str(uuid.uuid4()),
            user_id=f"USER{self.fake.random_number(digits=6)}",
            agent_id=f"AGENT{self.fake.random_number(digits=4)}",
            run_id=f"RUN{self.fake.random_number(digits=8)}",
            conversation=self.generate_conversation()
        )
    
    async def test_initialize(self):
        """Test connection pool initialization"""
        print("=" * 50)
        print("Testing Connection Pool Initialization")
        print("=" * 50)
        
        try:
            await self.service.initialize()
            pool_status = await self.service.get_connection_pool_status()
            print("✓ Connection pool initialized successfully")
            print(f"Connection pool status: {pool_status}")
            return True
        except Exception as e:
            print(f"✗ Connection pool initialization failed: {e}")
            return False
    
    async def test_create(self):
        """Test creating a single history record"""
        print("\n" + "=" * 50)
        print("Testing Single History Record Creation")
        print("=" * 50)
        
        try:
            history_record = self.generate_test_history_record()
            success = await self.service.create(history_record)
            
            if success:
                self.test_history_records.append(history_record)
                print(f"✓ History record created successfully - HID: {history_record.hid}")
                print(f"  User ID: {history_record.user_id}")
                print(f"  Agent ID: {history_record.agent_id}")
                print(f"  Run ID: {history_record.run_id}")
                
                # Parse and display conversation content
                conversation_data = json.loads(history_record.conversation)
                print(f"  Conversation rounds: {len(conversation_data['exchanges'])}")
                return True
            else:
                print("✗ Failed to create history record")
                return False
        except Exception as e:
            print(f"✗ Exception occurred while creating history record: {e}")
            return False
    
    async def test_batch_create(self):
        """Test batch creation of history records"""
        print("\n" + "=" * 50)
        print("Testing Batch History Record Creation")
        print("=" * 50)
        
        try:
            history_records = [self.generate_test_history_record() for _ in range(3)]
            success = await self.service.batch_create(history_records)
            
            if success:
                self.test_history_records.extend(history_records)
                print(f"✓ Batch creation successful - Created {len(history_records)} records")
                for record in history_records:
                    conversation_data = json.loads(record.conversation)
                    print(f"  - HID: {record.hid}, User: {record.user_id}, Agent: {record.agent_id}, Conversation rounds: {len(conversation_data['exchanges'])}")
                return True
            else:
                print("✗ Batch creation failed")
                return False
        except Exception as e:
            print(f"✗ Exception occurred during batch creation: {e}")
            return False
    
    async def test_get_by_hid(self):
        """Test querying records by HID"""
        print("\n" + "=" * 50)
        print("Testing Query by HID")
        print("=" * 50)
        
        if not self.test_history_records:
            print("⚠ No test records, skipping this test")
            return True
        
        try:
            test_record = self.test_history_records[0]
            result = await self.service.get_by_hid(test_record.hid)
            
            if result and result.hid == test_record.hid:
                print(f"✓ Query by HID successful")
                print(f"  Retrieved record: {result.user_id} - {result.agent_id} - {result.run_id}")
                
                # Verify conversation content
                conversation_data = json.loads(result.conversation)
                print(f"  Conversation rounds: {len(conversation_data['exchanges'])}")
                if conversation_data['exchanges']:
                    first_exchange = conversation_data['exchanges'][0]
                    print(f"  Sample conversation - Human: {first_exchange['human'][:50]}...")
                    print(f"           Assistant: {first_exchange['assistant'][:50]}...")
                return True
            else:
                print("✗ Query by HID failed - Record does not exist or data does not match")
                return False
        except Exception as e:
            print(f"✗ Exception occurred during query by HID: {e}")
            return False
    
    async def test_get_by_user_agent_run(self):
        """Test querying records by user, agent, and run ID"""
        print("\n" + "=" * 50)
        print("Testing Query by User, Agent, and Run ID")
        print("=" * 50)
        
        if not self.test_history_records:
            print("⚠ No test records, skipping this test")
            return True
        
        try:
            test_record = self.test_history_records[0]
            results = await self.service.get_by_user_agent_run(
                test_record.user_id, 
                test_record.agent_id, 
                test_record.run_id
            )
            
            if results and len(results) > 0:
                print(f"✓ Query by user, agent, run ID successful - Found {len(results)} records")
                
                for i, result in enumerate(results[:2]):  # Display first 2 records
                    conversation_data = json.loads(result.conversation)
                    print(f"  Record {i+1}: HID: {result.hid}, Conversation rounds: {len(conversation_data['exchanges'])}")
                
                # Test query with limit
                limited_results = await self.service.get_by_user_agent_run(
                    test_record.user_id, 
                    test_record.agent_id, 
                    test_record.run_id,
                    limit=1
                )
                print(f"  Limited query returned: {len(limited_results)} records")
                return True
            else:
                print("✗ Query by user, agent, run ID failed - No records found")
                return False
        except Exception as e:
            print(f"✗ Exception occurred during query by user, agent, run ID: {e}")
            return False
    
    async def test_get_by_user_agent_run_with_different_data(self):
        """Test queries with different user, agent, and run ID combinations"""
        print("\n" + "=" * 50)
        print("Testing Queries with Different Combinations")
        print("=" * 50)
        
        try:
            # Create records with specific combinations for testing
            test_user = "TEST_USER_123"
            test_agent = "TEST_AGENT_456"
            test_run = "TEST_RUN_789"
            
            test_record = HistoryRecord(
                hid=str(uuid.uuid4()),
                user_id=test_user,
                agent_id=test_agent,
                run_id=test_run,
                conversation=self.generate_conversation(2)
            )
            
            # Create record
            await self.service.create(test_record)
            self.test_history_records.append(test_record)
            
            # Query specific combination
            results = await self.service.get_by_user_agent_run(test_user, test_agent, test_run)
            
            if results and len(results) > 0:
                print(f"✓ Specific combination query successful - Found {len(results)} records")
                for result in results:
                    print(f"  - HID: {result.hid}, User: {result.user_id}, Agent: {result.agent_id}")
                return True
            else:
                print("✗ Specific combination query failed")
                return False
        except Exception as e:
            print(f"✗ Exception occurred during specific combination query: {e}")
            return False
    
    async def test_delete(self):
        """Test deleting history records"""
        print("\n" + "=" * 50)
        print("Testing History Record Deletion")
        print("=" * 50)
        
        if not self.test_history_records:
            print("⚠ No test records, skipping this test")
            return True
        
        try:
            # Use the last record for deletion test
            test_record = self.test_history_records[-1]
            success = await self.service.delete(test_record.hid)
            
            if success:
                # Verify deletion was successful
                deleted_record = await self.service.get_by_hid(test_record.hid)
                if deleted_record is None:
                    print("✓ Record deletion successful")
                    # Remove from test records list
                    self.test_history_records.pop()
                    return True
                else:
                    print("✗ Record deletion failed - Record still exists")
                    return False
            else:
                print("✗ Record deletion failed")
                return False
        except Exception as e:
            print(f"✗ Exception occurred during record deletion: {e}")
            return False
    
    async def test_exists(self):
        """Test record existence check"""
        print("\n" + "=" * 50)
        print("Testing Record Existence Check")
        print("=" * 50)
        
        if not self.test_history_records:
            print("⚠ No test records, skipping this test")
            return True
        
        try:
            test_record = self.test_history_records[0]
            
            # Test existing record
            exists = await self.service.exists(test_record.hid)
            if exists:
                print("✓ Existence check successful - Record exists")
            else:
                print("✗ Existence check failed - Record should exist but check returned false")
                return False
            
            # Test non-existent record
            not_exists = await self.service.exists("non_existent_hid")
            if not not_exists:
                print("✓ Non-existence check successful - Record does not exist")
            else:
                print("✗ Non-existence check failed - Record should not exist but check returned true")
                return False
            
            return True
        except Exception as e:
            print(f"✗ Exception occurred during existence check: {e}")
            return False
    
    async def test_conversation_content(self):
        """Test conversation content structure and integrity"""
        print("\n" + "=" * 50)
        print("Testing Conversation Content Structure")
        print("=" * 50)
        
        try:
            # Create record with specific conversation structure
            test_conversation = {
                "exchanges": [
                    {
                        "human": "Hello, what can you help me with?",
                        "assistant": "I am an AI assistant, I can help you answer questions, provide information, and assist with various tasks.",
                        "timestamp": datetime.now().isoformat()
                    },
                    {
                        "human": "Can you tell me today's weather?",
                        "assistant": "Sorry, I cannot access real-time weather information. I recommend checking a weather forecast app or website for the latest weather conditions.",
                        "timestamp": datetime.now().isoformat()
                    }
                ]
            }
            
            test_record = HistoryRecord(
                hid=str(uuid.uuid4()),
                user_id="CONV_TEST_USER",
                agent_id="CONV_TEST_AGENT",
                run_id="CONV_TEST_RUN",
                conversation=json.dumps(test_conversation, ensure_ascii=False)
            )
            
            # Create record
            await self.service.create(test_record)
            self.test_history_records.append(test_record)
            
            # Query and verify conversation structure
            result = await self.service.get_by_hid(test_record.hid)
            if result:
                conversation_data = json.loads(result.conversation)
                
                # Verify conversation structure
                if ('exchanges' in conversation_data and 
                    len(conversation_data['exchanges']) == 2 and
                    'human' in conversation_data['exchanges'][0] and
                    'assistant' in conversation_data['exchanges'][0]):
                    
                    print("✓ Conversation content structure validation successful")
                    print(f"  Conversation rounds: {len(conversation_data['exchanges'])}")
                    for i, exchange in enumerate(conversation_data['exchanges']):
                        print(f"  Round {i+1} - Human: {exchange['human']}")
                        print(f"        Assistant: {exchange['assistant'][:50]}...")
                    return True
                else:
                    print("✗ Conversation content structure validation failed")
                    return False
            else:
                print("✗ Conversation content test failed - Record not found")
                return False
        except Exception as e:
            print(f"✗ Exception occurred during conversation content test: {e}")
            return False
    
    async def test_large_conversation(self):
        """Test storage of large conversation content"""
        print("\n" + "=" * 50)
        print("Testing Large Conversation Content")
        print("=" * 50)
        
        try:
            # Create record with multiple conversation rounds
            large_conversation = {
                "exchanges": []
            }
            
            for i in range(10):  # 10 rounds of conversation
                exchange = {
                    "human": f"This is the {i+1}th human question, with relatively long content." * 5,
                    "assistant": f"This is the {i+1}th AI response, also relatively long, containing detailed explanations and information." * 8,
                    "timestamp": datetime.now().isoformat()
                }
                large_conversation["exchanges"].append(exchange)
            
            test_record = HistoryRecord(
                hid=str(uuid.uuid4()),
                user_id="LARGE_CONV_USER",
                agent_id="LARGE_CONV_AGENT",
                run_id="LARGE_CONV_RUN",
                conversation=json.dumps(large_conversation, ensure_ascii=False)
            )
            
            # Create record
            success = await self.service.create(test_record)
            
            if success:
                self.test_history_records.append(test_record)
                print("✓ Large conversation content storage successful")
                
                # Verify data integrity
                result = await self.service.get_by_hid(test_record.hid)
                if result:
                    conversation_data = json.loads(result.conversation)
                    print(f"  Stored conversation rounds: {len(conversation_data['exchanges'])}")
                    print(f"  Conversation content length: {len(result.conversation)} characters")
                    return True
                else:
                    print("✗ Large conversation content verification failed")
                    return False
            else:
                print("✗ Large conversation content storage failed")
                return False
        except Exception as e:
            print(f"✗ Exception occurred during large conversation test: {e}")
            return False
    
    async def test_connection_pool_status(self):
        """Test connection pool status query"""
        print("\n" + "=" * 50)
        print("Testing Connection Pool Status Query")
        print("=" * 50)
        
        try:
            status = await self.service.get_connection_pool_status()
            print("✓ Connection pool status query successful")
            print(f"Connection pool status: {status}")
            return True
        except Exception as e:
            print(f"✗ Exception occurred during connection pool status query: {e}")
            return False
    
    async def run_all_tests(self):
        """Run all tests"""
        print("Starting AsyncHistoryService Tests")
        print("=" * 60)
        
        test_results = {}
        
        # Run various test methods
        tests = [
            ("initialize", self.test_initialize),
            ("create", self.test_create),
            ("batch_create", self.test_batch_create),
            ("get_by_hid", self.test_get_by_hid),
            ("get_by_user_agent_run", self.test_get_by_user_agent_run),
            ("get_by_user_agent_run_with_different_data", self.test_get_by_user_agent_run_with_different_data),
            ("conversation_content", self.test_conversation_content),
            ("large_conversation", self.test_large_conversation),
            ("delete", self.test_delete),
            ("exists", self.test_exists),
            ("connection_pool_status", self.test_connection_pool_status),
        ]
        
        for test_name, test_func in tests:
            try:
                result = await test_func()
                test_results[test_name] = result
            except Exception as e:
                print(f"❌ Test {test_name} encountered an exception: {e}")
                test_results[test_name] = False
        
        # Clean up test data
        await self.cleanup_test_data()
        
        # Close connection pool
        await self.service.close()
        
        # Output test results summary
        print("\n" + "=" * 60)
        print("Test Results Summary")
        print("=" * 60)
        
        passed = sum(1 for result in test_results.values() if result)
        total = len(test_results)
        
        for test_name, result in test_results.items():
            status = "✓ Passed" if result else "✗ Failed"
            print(f"{test_name:45} {status}")
        
        print(f"\nTotal tests: {total}, Passed: {passed}, Failed: {total - passed}")
        print(f"Test completion rate: {passed/total*100:.1f}%")
        
        return all(test_results.values())
    
    async def cleanup_test_data(self):
        """Clean up test data"""
        if not self.test_history_records:
            return
        
        print("\n" + "=" * 50)
        print("Cleaning Up Test Data")
        print("=" * 50)
        
        try:
            deleted_count = 0
            for record in self.test_history_records:
                try:
                    await self.service.delete(record.hid)
                    deleted_count += 1
                except:
                    continue  # Ignore deletion errors
            
            print(f"✓ Cleaned up {deleted_count} test records")
        except Exception as e:
            print(f"⚠ Error occurred while cleaning up test data: {e}")


async def main():
    """Main function"""
    tester = HistoryServiceTester()
    
    try:
        success = await tester.run_all_tests()
        
        if success:
            print("\n🎉 All tests passed!")
            return 0
        else:
            print("\n❌ Some tests failed!")
            return 1
    except Exception as e:
        print(f"\n💥 Exception occurred during test execution: {e}")
        return 1


if __name__ == "__main__":
    # Installation command for dependencies (if not already installed):
    # pip install faker aiomysql pymysql
    
    exit_code = asyncio.run(main())
    exit(exit_code)
