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

from data_services.signature.signature import AsyncSignatureService
from data_services.api.base import Signature


class SignatureServiceTester:
    def __init__(self):
        self.service = AsyncSignatureService(pool_size=50)
        self.fake = Faker()
        self.test_signatures = []
    
    def generate_test_signature(self) -> Signature:
        return Signature(
            sig_type=random.choice(['application', 'database', 'api', 'file_system']),
            discovery_mode=random.choice(['auto', 'manual']),
            fingerprint=f"FP{self.fake.random_number(digits=6)}",
            location_info={"ip": self.fake.ipv4(), "url": self.fake.url()},
            metadata_content={"summary": self.fake.text(max_nb_chars=200), "type": "test"},
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
        """Test creating a single signature record"""
        print("\n" + "=" * 50)
        print("Testing single signature record creation")
        print("=" * 50)
        
        try:
            signature = self.generate_test_signature()
            success = await self.service.create(signature)
            
            if success:
                self.test_signatures.append(signature)
                print(f"✓ Record created successfully - Sig ID: {signature.sig_id}")
                print(f"  Fingerprint: {signature.fingerprint}")
                print(f"  Sig Type: {signature.sig_type}, Discovery Mode: {signature.discovery_mode}")
                print(f"  DD info: {signature.dd_namespace}/{signature.dd_name}")
                return True
            else:
                print("✗ Record creation failed")
                return False
        except Exception as e:
            print(f"✗ Record creation exception: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    async def test_batch_create(self):
        """Test batch creation of signature records"""
        print("\n" + "=" * 50)
        print("Testing batch creation of signature records")
        print("=" * 50)
        
        try:
            signatures = [self.generate_test_signature() for _ in range(5)]
            success = await self.service.batch_create(signatures)
            
            if success:
                self.test_signatures.extend(signatures)
                print(f"✓ Batch creation successful - created {len(signatures)} records")
                for sig in signatures:
                    print(f"  - Sig ID: {sig.sig_id}, Fingerprint: {sig.fingerprint}, DD: {sig.dd_namespace}/{sig.dd_name}")
                return True
            else:
                print("✗ Batch creation failed")
                return False
        except Exception as e:
            print(f"✗ Batch creation exception: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    async def test_get_by_fid(self):
        """Test querying records by sig_id"""
        print("\n" + "=" * 50)
        print("Testing record query by sig_id")
        print("=" * 50)
        
        if not self.test_signatures:
            print("⚠ No test records, skipping this test")
            return True
        
        try:
            test_sig = self.test_signatures[0]
            result = await self.service.get_by_fid(test_sig.sig_id)
            
            if result and result.sig_id == test_sig.sig_id:
                print(f"✓ Query by sig_id successful")
                print(f"  Found record: {result.fingerprint}")
                print(f"  DD info: {result.dd_namespace}/{result.dd_name}")
                return True
            else:
                print("✗ Query by sig_id failed - record doesn't exist or data doesn't match")
                return False
        except Exception as e:
            print(f"✗ Query by sig_id exception: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    async def test_get_by_signature_id(self):
        """Test querying records by fingerprint"""
        print("\n" + "=" * 50)
        print("Testing record query by fingerprint")
        print("=" * 50)
        
        if not self.test_signatures:
            print("⚠ No test records, skipping this test")
            return True
        
        try:
            test_sig = self.test_signatures[0]
            result = await self.service.get_by_signature_id(test_sig.fingerprint)
            
            if result and result.fingerprint == test_sig.fingerprint:
                print(f"✓ Query by fingerprint successful")
                print(f"  Found record: {result.sig_id}")
                print(f"  DD info: {result.dd_namespace}/{result.dd_name}")
                return True
            else:
                print("✗ Query by fingerprint failed - record doesn't exist or data doesn't match")
                return False
        except Exception as e:
            print(f"✗ Query by fingerprint exception: {e}")
            import traceback
            traceback.print_exc()
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
                    print(f"  {i+1}. {record.fingerprint} - DD: {record.dd_namespace}/{record.dd_name}")
            
            return True
        except Exception as e:
            print(f"✗ Retrieve all records exception: {e}")
            return False
    
    async def test_update(self):
        """Test updating records"""
        print("\n" + "=" * 50)
        print("Testing record update")
        print("=" * 50)
        
        if not self.test_signatures:
            print("⚠ No test records, skipping this test")
            return True
        
        try:
            test_sig = self.test_signatures[0]
            
            # Create update data
            updated_sig = Signature(
                sig_id=test_sig.sig_id,  # Keep same sig_id
                sig_type=test_sig.sig_type,
                discovery_mode=test_sig.discovery_mode,
                fingerprint=f"UPDATED_{test_sig.fingerprint}",
                location_info={"ip": "192.168.1.100", "url": "https://updated.example.com"},
                metadata_content={"summary": "Updated signature summary", "type": "updated"},
                dd_namespace="updated_namespace",  # Update dd_namespace
                dd_name="updated_name"            # Update dd_name
            )
            
            success = await self.service.update(test_sig.sig_id, updated_sig)
            
            if success:
                # Verify update was successful
                verified_sig = await self.service.get_by_fid(test_sig.sig_id)
                if verified_sig and verified_sig.fingerprint == updated_sig.fingerprint:
                    print("✓ Record update successful")
                    print(f"  Original fingerprint: {test_sig.fingerprint}")
                    print(f"  New fingerprint: {verified_sig.fingerprint}")
                    print(f"  New DD info: {verified_sig.dd_namespace}/{verified_sig.dd_name}")
                    return True
                else:
                    print("✗ Record update failed - verification failed")
                    return False
            else:
                print("✗ Record update failed")
                return False
        except Exception as e:
            print(f"✗ Record update exception: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    async def test_delete(self):
        """Test deleting records"""
        print("\n" + "=" * 50)
        print("Testing record deletion")
        print("=" * 50)
        
        if not self.test_signatures:
            print("⚠ No test records, skipping this test")
            return True
        
        try:
            # Use the last record for deletion test
            test_sig = self.test_signatures[-1]
            success = await self.service.delete(test_sig.sig_id)
            
            if success:
                # Verify deletion was successful
                deleted_sig = await self.service.get_by_fid(test_sig.sig_id)
                if deleted_sig is None:
                    print("✓ Record deletion successful")
                    # Remove from test records list
                    self.test_signatures.pop()
                    return True
                else:
                    print("✗ Record deletion failed - record still exists")
                    return False
            else:
                print("✗ Record deletion failed")
                return False
        except Exception as e:
            print(f"✗ Record deletion exception: {e}")
            import traceback
            traceback.print_exc()
            return False

    async def test_exists(self):
        """Test record existence check"""
        print("\n" + "=" * 50)
        print("Testing record existence check")
        print("=" * 50)
        
        if not self.test_signatures:
            print("⚠ No test records, skipping this test")
            return True
        
        try:
            test_sig = self.test_signatures[0]
            
            # Test existing record
            exists = await self.service.exists(test_sig.sig_id)
            if exists:
                print("✓ Existence check successful - record exists")
            else:
                print("✗ Existence check failed - record should exist but check shows it doesn't")
                return False
            
            # Test non-existing record
            not_exists = await self.service.exists("non_existent_sig_id")
            if not not_exists:
                print("✓ Non-existence check successful - record doesn't exist")
            else:
                print("✗ Non-existence check failed - record shouldn't exist but check shows it does")
                return False
            
            return True
        except Exception as e:
            print(f"✗ Existence check exception: {e}")
            import traceback
            traceback.print_exc()
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
        
        if not self.test_signatures:
            print("⚠ No test records, skipping this test")
            return True
        
        try:
            # Use current DD info from first record (may have been updated)
            test_sig = self.test_signatures[0]
            
            # Re-fetch latest data from database to ensure DD info is current
            latest_sig = await self.service.get_by_fid(test_sig.sig_id)
            if not latest_sig:
                print("⚠ Unable to get latest record info, skipping this test")
                return True
                
            results = await self.service.get_by_dd_info(latest_sig.dd_namespace, latest_sig.dd_name)
            
            if results and len(results) > 0:
                print(f"✓ Query by DD info successful - found {len(results)} records")
                for result in results[:3]:  # Only show first 3
                    print(f"  - {result.fingerprint} - {result.dd_namespace}/{result.dd_name}")
                return True
            else:
                print("✗ Query by DD info failed - no records found")
                # Debug info: show current DD info being used
                print(f"  DD info used: {latest_sig.dd_namespace}/{latest_sig.dd_name}")
                return False
        except Exception as e:
            print(f"✗ Query by DD info exception: {e}")
            import traceback
            traceback.print_exc()
            return False

    async def test_delete_by_dd_info(self):
        """Test deleting records by DD info"""
        print("\n" + "=" * 50)
        print("Testing record deletion by DD info")
        print("=" * 50)
        
        if not self.test_signatures:
            print("⚠ No test records, skipping this test")
            return True
        
        try:
            # Create some test records with specific DD info
            test_dd_namespace = "test_namespace_delete"
            test_dd_name = "test_name_delete"
            
            test_sig = Signature(
                sig_type='application',
                discovery_mode='auto',
                fingerprint=f"DELETE_TEST_{self.fake.random_number(digits=6)}",
                location_info={"ip": self.fake.ipv4()},
                metadata_content={"summary": "Record for deletion testing", "type": "test"},
                dd_namespace=test_dd_namespace,
                dd_name=test_dd_name
            )
            
            # Create record
            await self.service.create(test_sig)
            
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
            import traceback
            traceback.print_exc()
            return False

    async def test_exists_by_dd_info(self):
        """Test existence check by DD info"""
        print("\n" + "=" * 50)
        print("Testing existence check by DD info")
        print("=" * 50)
        
        if not self.test_signatures:
            print("⚠ No test records, skipping this test")
            return True
        
        try:
            # Use current DD info from first record
            test_sig = self.test_signatures[0]
            
            # Re-fetch latest data from database
            latest_sig = await self.service.get_by_fid(test_sig.sig_id)
            if not latest_sig:
                print("⚠ Unable to get latest record info, skipping this test")
                return True
            
            # Test existing records (using latest DD info)
            exists = await self.service.exists_by_dd_info(latest_sig.dd_namespace, latest_sig.dd_name)
            if exists:
                print("✓ DD info existence check successful - records exist")
            else:
                print("✗ DD info existence check failed - records should exist but check shows they don't")
                print(f"  DD info used: {latest_sig.dd_namespace}/{latest_sig.dd_name}")
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
            import traceback
            traceback.print_exc()
            return False
    
    async def run_all_tests(self):
        """Run all tests"""
        print("Starting AsyncSignatureService tests")
        print("=" * 60)
        
        test_results = {}
        
        # Run each test method
        tests = [
            ("initialize", self.test_initialize),
            ("create", self.test_create),
            ("batch_create", self.test_batch_create),
            ("get_by_fid", self.test_get_by_fid),
            ("get_by_signature_id", self.test_get_by_signature_id),
            ("get_all", self.test_get_all),
            ("update", self.test_update),
            ("delete", self.test_delete),
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
        if not self.test_signatures:
            return
        
        print("\n" + "=" * 50)
        print("Cleaning up test data")
        print("=" * 50)
        
        try:
            deleted_count = 0
            for sig in self.test_signatures:
                try:
                    await self.service.delete(sig.sig_id)
                    deleted_count += 1
                except:
                    continue  # Ignore deletion errors
            
            print(f"✓ Cleaned up {deleted_count} test records")
        except Exception as e:
            print(f"⚠ Error occurred during test data cleanup: {e}")


async def main():
    """Main function"""
    tester = SignatureServiceTester()
    
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
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    # Installation command for dependencies (if not already installed):
    # pip install faker aiomysql pymysql
    
    exit_code = asyncio.run(main())
    exit(exit_code)
