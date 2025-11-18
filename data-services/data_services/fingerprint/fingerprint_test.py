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

from data_services.fingerprint.fingerprint import AsyncFingerprintService, Fingerprint


class FingerprintServiceTester:
    def __init__(self):
        self.service = AsyncFingerprintService(pool_size=50)
        self.fake = Faker()
        self.test_fingerprints = []
    
    def generate_test_fingerprint(self) -> Fingerprint:
        return Fingerprint(
            fingerprint_id=f"FP{self.fake.random_number(digits=6)}",
            fingerprint_summary=self.fake.text(max_nb_chars=200),
            agent_info_name=self.fake.word(),
            agent_info_description=self.fake.sentence(),
            dd_namespace=self.fake.word(),
            dd_name=self.fake.word()
        )
    
    async def test_initialize(self):
        print("=" * 50)
        print("Testing connection pool initialization")
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
        """Test creating a single fingerprint record"""
        print("\n" + "=" * 50)
        print("Testing single fingerprint record creation")
        print("=" * 50)
        
        try:
            fingerprint = self.generate_test_fingerprint()
            success = await self.service.create(fingerprint)
            
            if success:
                self.test_fingerprints.append(fingerprint)
                print(f"✓ Record created successfully - FID: {fingerprint.fid}")
                print(f"  Fingerprint ID: {fingerprint.fingerprint_id}")
                print(f"  DD info: {fingerprint.dd_namespace}/{fingerprint.dd_name}")
                return True
            else:
                print("✗ Record creation failed")
                return False
        except Exception as e:
            print(f"✗ Record creation exception: {e}")
            return False
    
    async def test_batch_create(self):
        """Test batch creation of fingerprint records"""
        print("\n" + "=" * 50)
        print("Testing batch creation of fingerprint records")
        print("=" * 50)
        
        try:
            fingerprints = [self.generate_test_fingerprint() for _ in range(5)]
            success = await self.service.batch_create(fingerprints)
            
            if success:
                self.test_fingerprints.extend(fingerprints)
                print(f"✓ Batch creation successful - created {len(fingerprints)} records")
                for fp in fingerprints:
                    print(f"  - FID: {fp.fid}, Fingerprint ID: {fp.fingerprint_id}, DD: {fp.dd_namespace}/{fp.dd_name}")
                return True
            else:
                print("✗ Batch creation failed")
                return False
        except Exception as e:
            print(f"✗ Batch creation exception: {e}")
            return False
    
    async def test_get_by_fid(self):
        """Test querying records by FID"""
        print("\n" + "=" * 50)
        print("Testing record query by FID")
        print("=" * 50)
        
        if not self.test_fingerprints:
            print("⚠ No test records, skipping this test")
            return True
        
        try:
            test_fp = self.test_fingerprints[0]
            result = await self.service.get_by_fid(test_fp.fid)
            
            if result and result.fid == test_fp.fid:
                print(f"✓ Query by FID successful")
                print(f"  Found record: {result.fingerprint_id} - {result.agent_info_name}")
                print(f"  DD info: {result.dd_namespace}/{result.dd_name}")
                return True
            else:
                print("✗ Query by FID failed - record doesn't exist or data doesn't match")
                return False
        except Exception as e:
            print(f"✗ Query by FID exception: {e}")
            return False
    
    async def test_get_by_fingerprint_id(self):
        """Test querying records by fingerprint ID"""
        print("\n" + "=" * 50)
        print("Testing record query by fingerprint ID")
        print("=" * 50)
        
        if not self.test_fingerprints:
            print("⚠ No test records, skipping this test")
            return True
        
        try:
            test_fp = self.test_fingerprints[0]
            result = await self.service.get_by_fingerprint_id(test_fp.fingerprint_id)
            
            if result and result.fingerprint_id == test_fp.fingerprint_id:
                print(f"✓ Query by fingerprint ID successful")
                print(f"  Found record: {result.fid} - {result.agent_info_name}")
                print(f"  DD info: {result.dd_namespace}/{result.dd_name}")
                return True
            else:
                print("✗ Query by fingerprint ID failed - record doesn't exist or data doesn't match")
                return False
        except Exception as e:
            print(f"✗ Query by fingerprint ID exception: {e}")
            return False
    
    async def test_get_all(self):
        """Test retrieving all records"""
        print("\n" + "=" * 50)
        print("Testing retrieval of all records")
        print("=" * 50)
        
        try:
            # Test without pagination
            all_records = await self.service.get_all()
            print(f"✓ Retrieved all records successfully - total {len(all_records)} records")
            
            # Test with pagination
            page_records = await self.service.get_all(page=1, page_size=3)
            print(f"✓ Paginated query successful - Page 1, 3 per page, actually returned {len(page_records)} records")
            
            if all_records:
                print("First 3 record examples:")
                for i, record in enumerate(all_records[:3]):
                    print(f"  {i+1}. {record.fingerprint_id} - {record.agent_info_name} - DD: {record.dd_namespace}/{record.dd_name}")
            
            return True
        except Exception as e:
            print(f"✗ Retrieve all records exception: {e}")
            return False
    
    async def test_update(self):
        """Test updating records"""
        print("\n" + "=" * 50)
        print("Testing record update")
        print("=" * 50)
        
        if not self.test_fingerprints:
            print("⚠ No test records, skipping this test")
            return True
        
        try:
            test_fp = self.test_fingerprints[0]
            
            # Create update data
            updated_fp = Fingerprint(
                fid=test_fp.fid,  # Keep same FID
                fingerprint_id=f"UPDATED_{test_fp.fingerprint_id}",
                fingerprint_summary="Updated fingerprint summary",
                agent_info_name="Updated agent name",
                agent_info_description="Updated agent description",
                dd_namespace="updated_namespace",  # Update dd_namespace
                dd_name="updated_name"            # Update dd_name
            )
            
            success = await self.service.update(test_fp.fid, updated_fp)
            
            if success:
                # Verify update was successful
                verified_fp = await self.service.get_by_fid(test_fp.fid)
                if verified_fp and verified_fp.fingerprint_id == updated_fp.fingerprint_id:
                    print("✓ Record update successful")
                    print(f"  Original fingerprint ID: {test_fp.fingerprint_id}")
                    print(f"  New fingerprint ID: {verified_fp.fingerprint_id}")
                    print(f"  New DD info: {verified_fp.dd_namespace}/{verified_fp.dd_name}")
                    return True
                else:
                    print("✗ Record update failed - verification failed")
                    return False
            else:
                print("✗ Record update failed")
                return False
        except Exception as e:
            print(f"✗ Record update exception: {e}")
            return False
    
    async def test_delete(self):
        """Test deleting records"""
        print("\n" + "=" * 50)
        print("Testing record deletion")
        print("=" * 50)
        
        if not self.test_fingerprints:
            print("⚠ No test records, skipping this test")
            return True
        
        try:
            # Use the last record for deletion test
            test_fp = self.test_fingerprints[-1]
            success = await self.service.delete(test_fp.fid)
            
            if success:
                # Verify deletion was successful
                deleted_fp = await self.service.get_by_fid(test_fp.fid)
                if deleted_fp is None:
                    print("✓ Record deletion successful")
                    # Remove from test records list
                    self.test_fingerprints.pop()
                    return True
                else:
                    print("✗ Record deletion failed - record still exists")
                    return False
            else:
                print("✗ Record deletion failed")
                return False
        except Exception as e:
            print(f"✗ Record deletion exception: {e}")
            return False
    
    async def test_count(self):
        """Test record counting"""
        print("\n" + "=" * 50)
        print("Testing record counting")
        print("=" * 50)
        
        try:
            total_count = await self.service.count()
            print(f"✓ Total record count: {total_count}")
            
            # Test conditional counting
            if self.test_fingerprints:
                test_fp = self.test_fingerprints[0]
                condition_count = await self.service.count(
                    condition="agent_info_name = %s", 
                    params=(test_fp.agent_info_name,)
                )
                print(f"✓ Conditional record count: {condition_count}")
            
            # Test DD info conditional counting
            if self.test_fingerprints:
                test_fp = self.test_fingerprints[0]
                dd_condition_count = await self.service.count(
                    condition="dd_namespace = %s AND dd_name = %s", 
                    params=(test_fp.dd_namespace, test_fp.dd_name)
                )
                print(f"✓ DD info conditional record count: {dd_condition_count}")
            
            return True
        except Exception as e:
            print(f"✗ Record counting exception: {e}")
            return False
    
    async def test_exists(self):
        """Test record existence check"""
        print("\n" + "=" * 50)
        print("Testing record existence check")
        print("=" * 50)
        
        if not self.test_fingerprints:
            print("⚠ No test records, skipping this test")
            return True
        
        try:
            test_fp = self.test_fingerprints[0]
            
            # Test existing record
            exists = await self.service.exists(test_fp.fid)
            if exists:
                print("✓ Existence check successful - record exists")
            else:
                print("✗ Existence check failed - record should exist but check shows it doesn't")
                return False
            
            # Test non-existing record
            not_exists = await self.service.exists("non_existent_fid")
            if not not_exists:
                print("✓ Non-existence check successful - record doesn't exist")
            else:
                print("✗ Non-existence check failed - record shouldn't exist but check shows it does")
                return False
            
            return True
        except Exception as e:
            print(f"✗ Existence check exception: {e}")
            return False
    
    async def test_connection_pool_status(self):
        """Test connection pool status query"""
        print("\n" + "=" * 50)
        print("Testing connection pool status query")
        print("=" * 50)
        
        try:
            status = await self.service.get_connection_pool_status()
            print("✓ Connection pool status query successful")
            print(f"Connection pool status: {status}")
            return True
        except Exception as e:
            print(f"✗ Connection pool status query exception: {e}")
            return False

    async def test_get_by_dd_info(self):
        """Test querying records by DD info"""
        print("\n" + "=" * 50)
        print("Testing record query by DD info")
        print("=" * 50)
        
        if not self.test_fingerprints:
            print("⚠ No test records, skipping this test")
            return True
        
        try:
            # Use current DD info from first record (may have been updated)
            test_fp = self.test_fingerprints[0]
            
            # Re-fetch latest data from database to ensure DD info is current
            latest_fp = await self.service.get_by_fid(test_fp.fid)
            if not latest_fp:
                print("⚠ Unable to get latest record info, skipping this test")
                return True
                
            results = await self.service.get_by_dd_info(latest_fp.dd_namespace, latest_fp.dd_name)
            
            if results and len(results) > 0:
                print(f"✓ Query by DD info successful - found {len(results)} records")
                for result in results[:3]:  # Only show first 3
                    print(f"  - {result.fingerprint_id} - {result.dd_namespace}/{result.dd_name}")
                return True
            else:
                print("✗ Query by DD info failed - no records found")
                # Debug info: show current DD info being used
                print(f"  DD info used: {latest_fp.dd_namespace}/{latest_fp.dd_name}")
                return False
        except Exception as e:
            print(f"✗ Query by DD info exception: {e}")
            return False

    async def test_delete_by_dd_info(self):
        """Test deleting records by DD info"""
        print("\n" + "=" * 50)
        print("Testing record deletion by DD info")
        print("=" * 50)
        
        if not self.test_fingerprints:
            print("⚠ No test records, skipping this test")
            return True
        
        try:
            # Create some test records with specific DD info
            test_dd_namespace = "test_namespace_delete"
            test_dd_name = "test_name_delete"
            
            test_fp = Fingerprint(
                fingerprint_id=f"DELETE_TEST_{self.fake.random_number(digits=6)}",
                fingerprint_summary="Record for deletion testing",
                agent_info_name="test_agent",
                agent_info_description="Test agent",
                dd_namespace=test_dd_namespace,
                dd_name=test_dd_name
            )
            
            # Create record
            await self.service.create(test_fp)
            
            # Delete record
            success = await self.service.delete_by_dd_info(test_dd_namespace, test_dd_name)
            
            if success:
                # Verify deletion
                results = await self.service.get_by_dd_info(test_dd_namespace, test_dd_name)
                if len(results) == 0:
                    print("✓ Deletion by DD info successful")
                    return True
                else:
                    print("✗ Deletion by DD info failed - records still exist")
                    return False
            else:
                print("✗ Deletion by DD info failed")
                return False
        except Exception as e:
            print(f"✗ Deletion by DD info exception: {e}")
            return False

    async def test_exists_by_dd_info(self):
        """Test existence check by DD info"""
        print("\n" + "=" * 50)
        print("Testing existence check by DD info")
        print("=" * 50)
        
        if not self.test_fingerprints:
            print("⚠ No test records, skipping this test")
            return True
        
        try:
            # Use current DD info from first record
            test_fp = self.test_fingerprints[0]
            
            # Re-fetch latest data from database
            latest_fp = await self.service.get_by_fid(test_fp.fid)
            if not latest_fp:
                print("⚠ Unable to get latest record info, skipping this test")
                return True
            
            # Test existing records (using latest DD info)
            exists = await self.service.exists_by_dd_info(latest_fp.dd_namespace, latest_fp.dd_name)
            if exists:
                print("✓ DD info existence check successful - records exist")
            else:
                print("✗ DD info existence check failed - records should exist but check shows they don't")
                print(f"  DD info used: {latest_fp.dd_namespace}/{latest_fp.dd_name}")
                return False
            
            # Test non-existing records
            not_exists = await self.service.exists_by_dd_info("non_existent_namespace", "non_existent_name")
            if not not_exists:
                print("✓ DD info non-existence check successful - records don't exist")
            else:
                print("✗ DD info non-existence check failed - records shouldn't exist but check shows they do")
                return False
            
            return True
        except Exception as e:
            print(f"✗ DD info existence check exception: {e}")
            return False
    
    async def run_all_tests(self):
        """Run all tests"""
        print("Starting AsyncFingerprintService tests")
        print("=" * 60)
        
        test_results = {}
        
        # Run each test method
        tests = [
            ("initialize", self.test_initialize),
            ("create", self.test_create),
            ("batch_create", self.test_batch_create),
            ("get_by_fid", self.test_get_by_fid),
            ("get_by_fingerprint_id", self.test_get_by_fingerprint_id),
            ("get_all", self.test_get_all),
            ("update", self.test_update),
            ("delete", self.test_delete),
            ("count", self.test_count),
            ("exists", self.test_exists),
            ("connection_pool_status", self.test_connection_pool_status),
            ("get_by_dd_info", self.test_get_by_dd_info),
            ("delete_by_dd_info", self.test_delete_by_dd_info),
            ("exists_by_dd_info", self.test_exists_by_dd_info),
        ]
        
        for test_name, test_func in tests:
            try:
                result = await test_func()
                test_results[test_name] = result
            except Exception as e:
                print(f"❌ Test {test_name} encountered exception: {e}")
                test_results[test_name] = False
        
        # Clean up test data
        await self.cleanup_test_data()
        
        # Close connection pool
        await self.service.close()
        
        # Output test result summary
        print("\n" + "=" * 60)
        print("Test Result Summary")
        print("=" * 60)
        
        passed = sum(1 for result in test_results.values() if result)
        total = len(test_results)
        
        for test_name, result in test_results.items():
            status = "✓ Passed" if result else "✗ Failed"
            print(f"{test_name:25} {status}")
        
        print(f"\nTotal tests: {total}, Passed: {passed}, Failed: {total - passed}")
        print(f"Test completion rate: {passed/total*100:.1f}%")
        
        return all(test_results.values())
    
    async def cleanup_test_data(self):
        """Clean up test data"""
        if not self.test_fingerprints:
            return
        
        print("\n" + "=" * 50)
        print("Cleaning up test data")
        print("=" * 50)
        
        try:
            deleted_count = 0
            for fp in self.test_fingerprints:
                try:
                    await self.service.delete(fp.fid)
                    deleted_count += 1
                except:
                    continue  # Ignore deletion errors
            
            print(f"✓ Cleaned up {deleted_count} test records")
        except Exception as e:
            print(f"⚠ Error occurred during test data cleanup: {e}")


async def main():
    """Main function"""
    tester = FingerprintServiceTester()
    
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
