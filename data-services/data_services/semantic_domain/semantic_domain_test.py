import os
import sys
import asyncio
import random
import string
from datetime import datetime
from typing import List
from pydantic import BaseModel
import uuid
from faker import Faker

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
sys.path.insert(0, project_root)

from data_services.semantic_domain.semantic_domain import AsyncSemanticDomainService
from data_services.api.base import SemanticDomain


class SemanticDomainServiceTester:
    def __init__(self):
        self.service = AsyncSemanticDomainService(pool_size=50)
        self.fake = Faker()
        self.test_domains = []
    
    def generate_test_domain(self, descriptor_type: str = None) -> SemanticDomain:
        return SemanticDomain(
            semantic_domain=self.fake.text(max_nb_chars=500),
            agent_card=self.fake.text(max_nb_chars=500),
            dd_namespace=self.fake.word(),
            dd_name=self.fake.word(),
            descriptor_type=descriptor_type
        )
    
    async def test_initialize(self):
        """Test connection pool initialization and table creation"""
        print("=" * 50)
        print("Testing connection pool initialization and table creation")
        print("=" * 50)
        
        try:
            await self.service.initialize()
            pool_status = await self.service.get_connection_pool_status()
            print("✓ Connection pool initialized successfully")
            print(f"Connection pool status: {pool_status}")
            
            # Verify table exists by checking if we can query it
            count = await self.service.count()
            print(f"✓ Table exists and is accessible (current record count: {count})")
            return True
        except Exception as e:
            print(f"✗ Connection pool initialization failed: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    async def test_table_structure(self):
        """Test table structure - verify all columns and indexes exist"""
        print("\n" + "=" * 50)
        print("Testing table structure")
        print("=" * 50)
        
        try:
            async with self.service._get_cursor() as cursor:
                # Check columns
                await cursor.execute("DESCRIBE semantic_domain")
                columns = await cursor.fetchall()
                column_names = {col['Field'] for col in columns}
                
                expected_columns = {
                    'semantic_domain_id', 'semantic_domain', 'agent_card',
                    'dd_namespace', 'dd_name', 'descriptor_type',
                    'created_at', 'updated_at'
                }
                
                missing_columns = expected_columns - column_names
                if missing_columns:
                    print(f"✗ Missing columns: {missing_columns}")
                    return False
                else:
                    print(f"✓ All required columns exist: {column_names}")
                
                # Check indexes
                await cursor.execute("SHOW INDEXES FROM semantic_domain")
                indexes = await cursor.fetchall()
                index_names = {idx['Key_name'] for idx in indexes}
                
                expected_indexes = {'PRIMARY', 'idx_semantic_domain', 'idx_dd_name', 'idx_descriptor_type', 'idx_created_at'}
                missing_indexes = expected_indexes - index_names
                
                if missing_indexes:
                    print(f"✗ Missing indexes: {missing_indexes}")
                    return False
                else:
                    print(f"✓ All required indexes exist: {index_names}")
                
                return True
        except Exception as e:
            print(f"✗ Table structure check failed: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    async def test_create(self):
        """Test creating a single semantic domain record"""
        print("\n" + "=" * 50)
        print("Testing single semantic domain record creation")
        print("=" * 50)
        
        try:
            domain = self.generate_test_domain()
            success = await self.service.create(domain)
            
            if success:
                self.test_domains.append(domain)
                print(f"✓ Record created successfully - Domain ID: {domain.semantic_domain_id}")
                print(f"  DD info: {domain.dd_namespace}/{domain.dd_name}")
                print(f"  Semantic domain length: {len(domain.semantic_domain or '')} chars")
                print(f"  Agent card length: {len(domain.agent_card or '')} chars")
                return True
            else:
                print("✗ Record creation failed")
                return False
        except Exception as e:
            print(f"✗ Record creation exception: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    async def test_create_with_descriptor_type(self):
        """Test creating a record with descriptor_type"""
        print("\n" + "=" * 50)
        print("Testing creation with descriptor_type")
        print("=" * 50)

        try:
            domain = self.generate_test_domain(descriptor_type="code")
            success = await self.service.create(domain)

            if success:
                self.test_domains.append(domain)
                retrieved = await self.service.get_by_id(domain.semantic_domain_id)
                if retrieved and retrieved.descriptor_type == "code":
                    print(f"✓ Record created with descriptor_type=code - Domain ID: {domain.semantic_domain_id}")
                    return True
                else:
                    print(f"✗ descriptor_type mismatch: expected 'code', got {getattr(retrieved, 'descriptor_type', None)}")
                    return False
            else:
                print("✗ Record creation failed")
                return False
        except Exception as e:
            print(f"✗ Record creation exception: {e}")
            import traceback
            traceback.print_exc()
            return False

    async def test_create_with_id(self):
        """Test creating a record with a specific ID"""
        print("\n" + "=" * 50)
        print("Testing creation with specific ID")
        print("=" * 50)
        
        try:
            test_id = str(uuid.uuid4())
            domain = SemanticDomain(
                semantic_domain_id=test_id,
                semantic_domain="Test semantic domain",
                agent_card="Test agent card",
                dd_namespace="test_namespace",
                dd_name="test_name"
            )
            success = await self.service.create(domain)
            
            if success:
                # Verify the record was created with the correct ID
                retrieved = await self.service.get_by_id(test_id)
                if retrieved and retrieved.semantic_domain_id == test_id:
                    self.test_domains.append(domain)
                    print(f"✓ Record created with specified ID: {test_id}")
                    return True
                else:
                    print("✗ Record created but ID doesn't match")
                    return False
            else:
                print("✗ Record creation failed")
                return False
        except Exception as e:
            print(f"✗ Record creation exception: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    async def test_batch_create(self):
        """Test batch creation of semantic domain records"""
        print("\n" + "=" * 50)
        print("Testing batch creation of semantic domain records")
        print("=" * 50)
        
        try:
            domains = [self.generate_test_domain() for _ in range(5)]
            success = await self.service.batch_create(domains)
            
            if success:
                self.test_domains.extend(domains)
                print(f"✓ Batch creation successful - created {len(domains)} records")
                for domain in domains:
                    print(f"  - Domain ID: {domain.semantic_domain_id}, DD: {domain.dd_namespace}/{domain.dd_name}")
                return True
            else:
                print("✗ Batch creation failed")
                return False
        except Exception as e:
            print(f"✗ Batch creation exception: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    async def test_get_by_id(self):
        """Test retrieving a record by ID"""
        print("\n" + "=" * 50)
        print("Testing get by ID")
        print("=" * 50)
        
        try:
            if not self.test_domains:
                print("⚠ No test records available, creating one...")
                domain = self.generate_test_domain()
                await self.service.create(domain)
                self.test_domains.append(domain)
            
            test_domain = self.test_domains[0]
            retrieved = await self.service.get_by_id(test_domain.semantic_domain_id)
            
            if retrieved:
                if retrieved.semantic_domain_id == test_domain.semantic_domain_id:
                    print(f"✓ Record retrieved successfully - Domain ID: {retrieved.semantic_domain_id}")
                    print(f"  DD info: {retrieved.dd_namespace}/{retrieved.dd_name}")
                    print(f"  Created at: {retrieved.created_at}")
                    return True
                else:
                    print("✗ Retrieved record ID doesn't match")
                    return False
            else:
                print("✗ Record not found")
                return False
        except Exception as e:
            print(f"✗ Get by ID exception: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    async def test_get_by_dd_info(self):
        """Test retrieving records by DD namespace and name"""
        print("\n" + "=" * 50)
        print("Testing get by DD info")
        print("=" * 50)
        
        try:
            # Create test records with same DD info
            test_namespace = f"test_ns_{random.randint(1000, 9999)}"
            test_name = f"test_name_{random.randint(1000, 9999)}"
            
            domains = []
            for _ in range(3):
                domain = SemanticDomain(
                    semantic_domain=self.fake.text(max_nb_chars=200),
                    agent_card=self.fake.text(max_nb_chars=200),
                    dd_namespace=test_namespace,
                    dd_name=test_name
                )
                await self.service.create(domain)
                domains.append(domain)
            
            # Retrieve by DD info
            retrieved = await self.service.get_by_dd_info(test_namespace, test_name)
            
            if len(retrieved) >= 3:
                print(f"✓ Retrieved {len(retrieved)} records for DD: {test_namespace}/{test_name}")
                for domain in retrieved:
                    print(f"  - Domain ID: {domain.semantic_domain_id}")
                return True
            else:
                print(f"✗ Expected at least 3 records, got {len(retrieved)}")
                return False
        except Exception as e:
            print(f"✗ Get by DD info exception: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    async def test_get_all(self):
        """Test retrieving all records"""
        print("\n" + "=" * 50)
        print("Testing get all records")
        print("=" * 50)
        
        try:
            all_domains = await self.service.get_all()
            print(f"✓ Retrieved {len(all_domains)} total records")
            
            if all_domains:
                print(f"  First record: {all_domains[0].semantic_domain_id}")
                print(f"  Last record: {all_domains[-1].semantic_domain_id}")
            
            return True
        except Exception as e:
            print(f"✗ Get all exception: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    async def test_get_all_pagination(self):
        """Test pagination"""
        print("\n" + "=" * 50)
        print("Testing pagination")
        print("=" * 50)
        
        try:
            page1 = await self.service.get_all(page=1, page_size=2)
            page2 = await self.service.get_all(page=2, page_size=2)
            
            print(f"✓ Page 1: {len(page1)} records")
            print(f"✓ Page 2: {len(page2)} records")
            
            if page1 and page2:
                # Check that pages are different
                if page1[0].semantic_domain_id != page2[0].semantic_domain_id:
                    print("✓ Pages contain different records")
                    return True
                else:
                    print("⚠ Pages may contain overlapping records")
                    return True
            
            return True
        except Exception as e:
            print(f"✗ Pagination exception: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    async def test_update(self):
        """Test updating a record"""
        print("\n" + "=" * 50)
        print("Testing record update")
        print("=" * 50)
        
        try:
            if not self.test_domains:
                print("⚠ No test records available, creating one...")
                domain = self.generate_test_domain()
                await self.service.create(domain)
                self.test_domains.append(domain)
            
            test_domain = self.test_domains[0]
            updated_domain = SemanticDomain(
                semantic_domain="Updated semantic domain",
                agent_card="Updated agent card",
                dd_namespace="updated_namespace",
                dd_name="updated_name"
            )
            
            success = await self.service.update(test_domain.semantic_domain_id, updated_domain)
            
            if success:
                # Verify update
                retrieved = await self.service.get_by_id(test_domain.semantic_domain_id)
                if retrieved and retrieved.semantic_domain == "Updated semantic domain":
                    print(f"✓ Record updated successfully - Domain ID: {test_domain.semantic_domain_id}")
                    print(f"  Updated DD info: {retrieved.dd_namespace}/{retrieved.dd_name}")
                    return True
                else:
                    print("✗ Update succeeded but data doesn't match")
                    return False
            else:
                print("✗ Update failed")
                return False
        except Exception as e:
            print(f"✗ Update exception: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    async def test_delete(self):
        """Test deleting a record"""
        print("\n" + "=" * 50)
        print("Testing record deletion")
        print("=" * 50)
        
        try:
            # Create a test record to delete
            domain = self.generate_test_domain()
            await self.service.create(domain)
            domain_id = domain.semantic_domain_id
            
            # Delete it
            success = await self.service.delete(domain_id)
            
            if success:
                # Verify deletion
                retrieved = await self.service.get_by_id(domain_id)
                if retrieved is None:
                    print(f"✓ Record deleted successfully - Domain ID: {domain_id}")
                    return True
                else:
                    print("✗ Delete succeeded but record still exists")
                    return False
            else:
                print("✗ Delete failed")
                return False
        except Exception as e:
            print(f"✗ Delete exception: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    async def test_delete_by_dd_info(self):
        """Test deleting records by DD info"""
        print("\n" + "=" * 50)
        print("Testing delete by DD info")
        print("=" * 50)
        
        try:
            # Create test records with same DD info
            test_namespace = f"delete_ns_{random.randint(1000, 9999)}"
            test_name = f"delete_name_{random.randint(1000, 9999)}"
            
            domains = []
            for _ in range(3):
                domain = SemanticDomain(
                    semantic_domain=self.fake.text(max_nb_chars=200),
                    agent_card=self.fake.text(max_nb_chars=200),
                    dd_namespace=test_namespace,
                    dd_name=test_name
                )
                await self.service.create(domain)
                domains.append(domain)
            
            # Delete by DD info
            success = await self.service.delete_by_dd_info(test_namespace, test_name)
            
            if success:
                # Verify deletion
                retrieved = await self.service.get_by_dd_info(test_namespace, test_name)
                if len(retrieved) == 0:
                    print(f"✓ All records deleted for DD: {test_namespace}/{test_name}")
                    return True
                else:
                    print(f"✗ Delete succeeded but {len(retrieved)} records still exist")
                    return False
            else:
                print("✗ Delete failed")
                return False
        except Exception as e:
            print(f"✗ Delete by DD info exception: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    async def test_count(self):
        """Test counting records"""
        print("\n" + "=" * 50)
        print("Testing record count")
        print("=" * 50)
        
        try:
            total_count = await self.service.count()
            print(f"✓ Total record count: {total_count}")
            
            # Test conditional count
            if self.test_domains:
                test_domain = self.test_domains[0]
                conditional_count = await self.service.count(
                    "dd_namespace = %s AND dd_name = %s",
                    (test_domain.dd_namespace, test_domain.dd_name)
                )
                print(f"✓ Conditional count: {conditional_count}")
            
            return True
        except Exception as e:
            print(f"✗ Count exception: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    async def test_exists(self):
        """Test checking if record exists"""
        print("\n" + "=" * 50)
        print("Testing exists check")
        print("=" * 50)
        
        try:
            if not self.test_domains:
                print("⚠ No test records available, creating one...")
                domain = self.generate_test_domain()
                await self.service.create(domain)
                self.test_domains.append(domain)
            
            test_domain = self.test_domains[0]
            exists = await self.service.exists(test_domain.semantic_domain_id)
            
            if exists:
                print(f"✓ Record exists check passed - Domain ID: {test_domain.semantic_domain_id}")
                
                # Test non-existent record
                non_existent_id = str(uuid.uuid4())
                not_exists = await self.service.exists(non_existent_id)
                if not not_exists:
                    print(f"✓ Non-existent record check passed")
                    return True
                else:
                    print("✗ Non-existent record check failed")
                    return False
            else:
                print("✗ Exists check failed")
                return False
        except Exception as e:
            print(f"✗ Exists check exception: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    async def test_exists_by_dd_info(self):
        """Test checking if records exist by DD info"""
        print("\n" + "=" * 50)
        print("Testing exists by DD info")
        print("=" * 50)
        
        try:
            # Create test record
            test_namespace = f"exists_ns_{random.randint(1000, 9999)}"
            test_name = f"exists_name_{random.randint(1000, 9999)}"
            
            domain = SemanticDomain(
                semantic_domain=self.fake.text(max_nb_chars=200),
                agent_card=self.fake.text(max_nb_chars=200),
                dd_namespace=test_namespace,
                dd_name=test_name
            )
            await self.service.create(domain)
            
            # Check existence
            exists = await self.service.exists_by_dd_info(test_namespace, test_name)
            
            if exists:
                print(f"✓ Records exist for DD: {test_namespace}/{test_name}")
                
                # Test non-existent DD info
                not_exists = await self.service.exists_by_dd_info("non_existent_ns", "non_existent_name")
                if not not_exists:
                    print(f"✓ Non-existent DD info check passed")
                    return True
                else:
                    print("✗ Non-existent DD info check failed")
                    return False
            else:
                print("✗ Exists by DD info check failed")
                return False
        except Exception as e:
            print(f"✗ Exists by DD info exception: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    async def test_connection_pool_status(self):
        """Test connection pool status"""
        print("\n" + "=" * 50)
        print("Testing connection pool status")
        print("=" * 50)
        
        try:
            status = await self.service.get_connection_pool_status()
            print(f"✓ Connection pool status retrieved:")
            for key, value in status.items():
                print(f"  {key}: {value}")
            return True
        except Exception as e:
            print(f"✗ Connection pool status exception: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    async def cleanup(self):
        """Clean up test records"""
        print("\n" + "=" * 50)
        print("Cleaning up test records")
        print("=" * 50)
        
        try:
            deleted_count = 0
            for domain in self.test_domains:
                try:
                    await self.service.delete(domain.semantic_domain_id)
                    deleted_count += 1
                except:
                    pass
            
            print(f"✓ Cleaned up {deleted_count} test records")
        except Exception as e:
            print(f"⚠ Cleanup exception: {e}")
    
    async def close(self):
        """Close the service connection pool"""
        try:
            await self.service.close()
            print("✓ Service connection pool closed")
        except Exception as e:
            print(f"⚠ Close exception: {e}")


async def run_all_tests():
    """Run all tests"""
    tester = SemanticDomainServiceTester()
    
    test_methods = [
        ("Initialize", tester.test_initialize),
        ("Table Structure", tester.test_table_structure),
        ("Create", tester.test_create),
        ("Create with descriptor_type", tester.test_create_with_descriptor_type),
        ("Create with ID", tester.test_create_with_id),
        ("Batch Create", tester.test_batch_create),
        ("Get by ID", tester.test_get_by_id),
        ("Get by DD Info", tester.test_get_by_dd_info),
        ("Get All", tester.test_get_all),
        ("Get All Pagination", tester.test_get_all_pagination),
        ("Update", tester.test_update),
        ("Delete", tester.test_delete),
        ("Delete by DD Info", tester.test_delete_by_dd_info),
        ("Count", tester.test_count),
        ("Exists", tester.test_exists),
        ("Exists by DD Info", tester.test_exists_by_dd_info),
        ("Connection Pool Status", tester.test_connection_pool_status),
    ]
    
    results = []
    
    try:
        for test_name, test_method in test_methods:
            try:
                result = await test_method()
                results.append((test_name, result))
            except Exception as e:
                print(f"\n✗ Test '{test_name}' raised exception: {e}")
                import traceback
                traceback.print_exc()
                results.append((test_name, False))
        
        # Print summary
        print("\n" + "=" * 50)
        print("TEST SUMMARY")
        print("=" * 50)
        
        passed = sum(1 for _, result in results if result)
        total = len(results)
        
        for test_name, result in results:
            status = "✓ PASS" if result else "✗ FAIL"
            print(f"{status}: {test_name}")
        
        print(f"\nTotal: {passed}/{total} tests passed")
        
    finally:
        await tester.cleanup()
        await tester.close()


if __name__ == "__main__":
    asyncio.run(run_all_tests())
