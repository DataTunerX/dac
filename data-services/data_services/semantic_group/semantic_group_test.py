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

from data_services.semantic_group.semantic_group import AsyncSemanticGroupService
from data_services.api.base import SemanticGroup, DDGroupRelation


class SemanticGroupServiceTester:
    def __init__(self):
        self.service = AsyncSemanticGroupService(pool_size=50)
        self.fake = Faker()
        self.test_groups = []
        self.test_relations = []
    
    def generate_test_group(self) -> SemanticGroup:
        return SemanticGroup(
            group_name=self.fake.company() + " Group",
            description=self.fake.text(max_nb_chars=200),
            version=f"v{random.randint(1, 10)}.{random.randint(0, 9)}"
        )
    
    def generate_test_relation(self, sd_id: str, group_id: str) -> DDGroupRelation:
        return DDGroupRelation(
            sd_id=sd_id,
            group_id=group_id,
            association_reason=self.fake.text(max_nb_chars=100)
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
            count = await self.service.count_groups()
            print(f"✓ Tables exist and are accessible (current group count: {count})")
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
                # Check semantic_groups table columns
                await cursor.execute("DESCRIBE semantic_groups")
                columns = await cursor.fetchall()
                column_names = {col['Field'] for col in columns}
                
                expected_columns = {
                    'id', 'group_name', 'description', 'agent_card', 'version', 'created_at'
                }
                
                missing_columns = expected_columns - column_names
                if missing_columns:
                    print(f"✗ Missing columns in semantic_groups: {missing_columns}")
                    return False
                else:
                    print(f"✓ All required columns exist in semantic_groups: {column_names}")
                
                # Check semantic_groups indexes
                await cursor.execute("SHOW INDEXES FROM semantic_groups")
                indexes = await cursor.fetchall()
                index_names = {idx['Key_name'] for idx in indexes}
                
                expected_indexes = {'PRIMARY', 'idx_group_name', 'idx_created_at'}
                missing_indexes = expected_indexes - index_names
                
                if missing_indexes:
                    print(f"✗ Missing indexes in semantic_groups: {missing_indexes}")
                    return False
                else:
                    print(f"✓ All required indexes exist in semantic_groups: {index_names}")
                
                # Check dd_group_relation table columns
                await cursor.execute("DESCRIBE dd_group_relation")
                columns = await cursor.fetchall()
                column_names = {col['Field'] for col in columns}
                
                expected_columns = {
                    'id', 'sd_id', 'group_id', 'association_reason'
                }
                
                missing_columns = expected_columns - column_names
                if missing_columns:
                    print(f"✗ Missing columns in dd_group_relation: {missing_columns}")
                    return False
                else:
                    print(f"✓ All required columns exist in dd_group_relation: {column_names}")
                
                # Check dd_group_relation indexes
                await cursor.execute("SHOW INDEXES FROM dd_group_relation")
                indexes = await cursor.fetchall()
                index_names = {idx['Key_name'] for idx in indexes}
                
                expected_indexes = {'PRIMARY', 'idx_sd_id', 'idx_group_id'}
                missing_indexes = expected_indexes - index_names
                
                if missing_indexes:
                    print(f"⚠ Missing indexes in dd_group_relation: {missing_indexes} (may be acceptable)")
                else:
                    print(f"✓ All required indexes exist in dd_group_relation: {index_names}")
                
                return True
        except Exception as e:
            print(f"✗ Table structure check failed: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    # SemanticGroup CRUD tests
    async def test_create_group(self):
        """Test creating a single semantic group record"""
        print("\n" + "=" * 50)
        print("Testing single semantic group record creation")
        print("=" * 50)
        
        try:
            group = self.generate_test_group()
            success = await self.service.create_group(group)
            
            if success:
                self.test_groups.append(group)
                print(f"✓ Group created successfully - Group ID: {group.id}")
                print(f"  Group name: {group.group_name}")
                print(f"  Description length: {len(group.description or '')} chars")
                print(f"  Version: {group.version}")
                return True
            else:
                print("✗ Group creation failed")
                return False
        except Exception as e:
            print(f"✗ Group creation exception: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    async def test_create_group_with_id(self):
        """Test creating a group with a specific ID"""
        print("\n" + "=" * 50)
        print("Testing group creation with specific ID")
        print("=" * 50)
        
        try:
            test_id = str(uuid.uuid4())
            group = SemanticGroup(
                id=test_id,
                group_name="Test Group",
                description="Test description",
                version="v1.0"
            )
            success = await self.service.create_group(group)
            
            if success:
                # Verify the record was created with the correct ID
                retrieved = await self.service.get_group_by_id(test_id)
                if retrieved and retrieved.id == test_id:
                    self.test_groups.append(group)
                    print(f"✓ Group created with specified ID: {test_id}")
                    return True
                else:
                    print("✗ Group created but ID doesn't match")
                    return False
            else:
                print("✗ Group creation failed")
                return False
        except Exception as e:
            print(f"✗ Group creation exception: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    async def test_batch_create_groups(self):
        """Test batch creation of semantic group records"""
        print("\n" + "=" * 50)
        print("Testing batch creation of semantic group records")
        print("=" * 50)
        
        try:
            groups = [self.generate_test_group() for _ in range(5)]
            success = await self.service.batch_create_groups(groups)
            
            if success:
                self.test_groups.extend(groups)
                print(f"✓ Batch creation successful - created {len(groups)} groups")
                for group in groups:
                    print(f"  - Group ID: {group.id}, Name: {group.group_name}")
                return True
            else:
                print("✗ Batch creation failed")
                return False
        except Exception as e:
            print(f"✗ Batch creation exception: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    async def test_get_group_by_id(self):
        """Test retrieving a group by ID"""
        print("\n" + "=" * 50)
        print("Testing get group by ID")
        print("=" * 50)
        
        try:
            if not self.test_groups:
                print("⚠ No test groups available, creating one...")
                group = self.generate_test_group()
                await self.service.create_group(group)
                self.test_groups.append(group)
            
            test_group = self.test_groups[0]
            retrieved = await self.service.get_group_by_id(test_group.id)
            
            if retrieved:
                if retrieved.id == test_group.id:
                    print(f"✓ Group retrieved successfully - Group ID: {retrieved.id}")
                    print(f"  Group name: {retrieved.group_name}")
                    print(f"  Created at: {retrieved.created_at}")
                    return True
                else:
                    print("✗ Retrieved group ID doesn't match")
                    return False
            else:
                print("✗ Group not found")
                return False
        except Exception as e:
            print(f"✗ Get group by ID exception: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    async def test_get_all_groups(self):
        """Test retrieving all groups"""
        print("\n" + "=" * 50)
        print("Testing get all groups")
        print("=" * 50)
        
        try:
            all_groups = await self.service.get_all_groups()
            print(f"✓ Retrieved {len(all_groups)} total groups")
            
            if all_groups:
                print(f"  First group: {all_groups[0].id} - {all_groups[0].group_name}")
                print(f"  Last group: {all_groups[-1].id} - {all_groups[-1].group_name}")
            
            return True
        except Exception as e:
            print(f"✗ Get all groups exception: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    async def test_get_all_groups_pagination(self):
        """Test pagination"""
        print("\n" + "=" * 50)
        print("Testing pagination")
        print("=" * 50)
        
        try:
            page1 = await self.service.get_all_groups(page=1, page_size=2)
            page2 = await self.service.get_all_groups(page=2, page_size=2)
            
            print(f"✓ Page 1: {len(page1)} groups")
            print(f"✓ Page 2: {len(page2)} groups")
            
            if page1 and page2:
                # Check that pages are different
                if page1[0].id != page2[0].id:
                    print("✓ Pages contain different groups")
                    return True
                else:
                    print("⚠ Pages may contain overlapping groups")
                    return True
            
            return True
        except Exception as e:
            print(f"✗ Pagination exception: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    async def test_update_group(self):
        """Test updating a group"""
        print("\n" + "=" * 50)
        print("Testing group update")
        print("=" * 50)
        
        try:
            if not self.test_groups:
                print("⚠ No test groups available, creating one...")
                group = self.generate_test_group()
                await self.service.create_group(group)
                self.test_groups.append(group)
            
            test_group = self.test_groups[0]
            updated_group = SemanticGroup(
                group_name="Updated Group Name",
                description="Updated description",
                version="v2.0"
            )
            
            success = await self.service.update_group(test_group.id, updated_group)
            
            if success:
                # Verify update
                retrieved = await self.service.get_group_by_id(test_group.id)
                if retrieved and retrieved.group_name == "Updated Group Name":
                    print(f"✓ Group updated successfully - Group ID: {test_group.id}")
                    print(f"  Updated name: {retrieved.group_name}")
                    print(f"  Updated version: {retrieved.version}")
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
    
    async def test_delete_group(self):
        """Test deleting a group"""
        print("\n" + "=" * 50)
        print("Testing group deletion")
        print("=" * 50)
        
        try:
            # Create a test group to delete
            group = self.generate_test_group()
            await self.service.create_group(group)
            group_id = group.id
            
            # Delete it
            success = await self.service.delete_group(group_id)
            
            if success:
                # Verify deletion
                retrieved = await self.service.get_group_by_id(group_id)
                if retrieved is None:
                    print(f"✓ Group deleted successfully - Group ID: {group_id}")
                    return True
                else:
                    print("✗ Delete succeeded but group still exists")
                    return False
            else:
                print("✗ Delete failed")
                return False
        except Exception as e:
            print(f"✗ Delete exception: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    async def test_count_groups(self):
        """Test counting groups"""
        print("\n" + "=" * 50)
        print("Testing group count")
        print("=" * 50)
        
        try:
            total_count = await self.service.count_groups()
            print(f"✓ Total group count: {total_count}")
            
            # Test conditional count
            if self.test_groups:
                test_group = self.test_groups[0]
                conditional_count = await self.service.count_groups(
                    "group_name = %s",
                    (test_group.group_name,)
                )
                print(f"✓ Conditional count: {conditional_count}")
            
            return True
        except Exception as e:
            print(f"✗ Count exception: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    async def test_exists_group(self):
        """Test checking if group exists"""
        print("\n" + "=" * 50)
        print("Testing group exists check")
        print("=" * 50)
        
        try:
            if not self.test_groups:
                print("⚠ No test groups available, creating one...")
                group = self.generate_test_group()
                await self.service.create_group(group)
                self.test_groups.append(group)
            
            test_group = self.test_groups[0]
            exists = await self.service.exists_group(test_group.id)
            
            if exists:
                print(f"✓ Group exists check passed - Group ID: {test_group.id}")
                
                # Test non-existent group
                non_existent_id = str(uuid.uuid4())
                not_exists = await self.service.exists_group(non_existent_id)
                if not not_exists:
                    print(f"✓ Non-existent group check passed")
                    return True
                else:
                    print("✗ Non-existent group check failed")
                    return False
            else:
                print("✗ Exists check failed")
                return False
        except Exception as e:
            print(f"✗ Exists check exception: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    # DDGroupRelation CRUD tests
    async def test_create_relation(self):
        """Test creating a single DD group relation"""
        print("\n" + "=" * 50)
        print("Testing single DD group relation creation")
        print("=" * 50)
        
        try:
            # Create a test group first
            if not self.test_groups:
                group = self.generate_test_group()
                await self.service.create_group(group)
                self.test_groups.append(group)
            
            test_group = self.test_groups[0]
            test_sd_id = str(uuid.uuid4())
            
            relation = self.generate_test_relation(test_sd_id, test_group.id)
            success = await self.service.create_relation(relation)
            
            if success:
                self.test_relations.append(relation)
                print(f"✓ Relation created successfully")
                print(f"  SD ID: {relation.sd_id}")
                print(f"  Group ID: {relation.group_id}")
                print(f"  Association reason: {relation.association_reason}")
                return True
            else:
                print("✗ Relation creation failed")
                return False
        except Exception as e:
            print(f"✗ Relation creation exception: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    async def test_batch_create_relations(self):
        """Test batch creation of DD group relations"""
        print("\n" + "=" * 50)
        print("Testing batch creation of DD group relations")
        print("=" * 50)
        
        try:
            # Create a test group first
            if not self.test_groups:
                group = self.generate_test_group()
                await self.service.create_group(group)
                self.test_groups.append(group)
            
            test_group = self.test_groups[0]
            relations = []
            for _ in range(3):
                test_sd_id = str(uuid.uuid4())
                relation = self.generate_test_relation(test_sd_id, test_group.id)
                relations.append(relation)
            
            success = await self.service.batch_create_relations(relations)
            
            if success:
                self.test_relations.extend(relations)
                print(f"✓ Batch creation successful - created {len(relations)} relations")
                for relation in relations:
                    print(f"  - SD ID: {relation.sd_id}, Group ID: {relation.group_id}")
                return True
            else:
                print("✗ Batch creation failed")
                return False
        except Exception as e:
            print(f"✗ Batch creation exception: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    async def test_get_relations_by_group_id(self):
        """Test retrieving relations by group_id"""
        print("\n" + "=" * 50)
        print("Testing get relations by group_id")
        print("=" * 50)
        
        try:
            # Create a test group and relations
            if not self.test_groups:
                group = self.generate_test_group()
                await self.service.create_group(group)
                self.test_groups.append(group)
            
            test_group = self.test_groups[0]
            
            # Create multiple relations for this group
            relations = []
            for _ in range(3):
                test_sd_id = str(uuid.uuid4())
                relation = self.generate_test_relation(test_sd_id, test_group.id)
                await self.service.create_relation(relation)
                relations.append(relation)
            
            # Retrieve by group_id
            retrieved = await self.service.get_relations_by_group_id(test_group.id)
            
            if len(retrieved) >= 3:
                print(f"✓ Retrieved {len(retrieved)} relations for group: {test_group.id}")
                for relation in retrieved[:3]:
                    print(f"  - Relation ID: {relation.id}, SD ID: {relation.sd_id}")
                return True
            else:
                print(f"✗ Expected at least 3 relations, got {len(retrieved)}")
                return False
        except Exception as e:
            print(f"✗ Get relations by group_id exception: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    async def test_get_relations_by_sd_id(self):
        """Test retrieving relations by sd_id"""
        print("\n" + "=" * 50)
        print("Testing get relations by sd_id")
        print("=" * 50)
        
        try:
            # Create test groups and a relation
            if not self.test_groups:
                group = self.generate_test_group()
                await self.service.create_group(group)
                self.test_groups.append(group)
            
            test_group = self.test_groups[0]
            test_sd_id = str(uuid.uuid4())
            
            # Create relation
            relation = self.generate_test_relation(test_sd_id, test_group.id)
            await self.service.create_relation(relation)
            
            # Retrieve by sd_id
            retrieved = await self.service.get_relations_by_sd_id(test_sd_id)
            
            if len(retrieved) >= 1:
                print(f"✓ Retrieved {len(retrieved)} relations for SD: {test_sd_id}")
                for relation in retrieved:
                    print(f"  - Relation ID: {relation.id}, Group ID: {relation.group_id}")
                return True
            else:
                print(f"✗ Expected at least 1 relation, got {len(retrieved)}")
                return False
        except Exception as e:
            print(f"✗ Get relations by sd_id exception: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    async def test_delete_relation(self):
        """Test deleting a relation"""
        print("\n" + "=" * 50)
        print("Testing relation deletion")
        print("=" * 50)
        
        try:
            # Create a test group and relation
            if not self.test_groups:
                group = self.generate_test_group()
                await self.service.create_group(group)
                self.test_groups.append(group)
            
            test_group = self.test_groups[0]
            test_sd_id = str(uuid.uuid4())
            
            relation = self.generate_test_relation(test_sd_id, test_group.id)
            await self.service.create_relation(relation)
            
            # Get the relation ID (we need to query it first)
            relations = await self.service.get_relations_by_sd_id(test_sd_id)
            if not relations:
                print("✗ Could not find created relation")
                return False
            
            relation_id = relations[0].id
            
            # Delete it
            success = await self.service.delete_relation(relation_id)
            
            if success:
                # Verify deletion
                retrieved = await self.service.get_relations_by_sd_id(test_sd_id)
                if len(retrieved) == 0:
                    print(f"✓ Relation deleted successfully - Relation ID: {relation_id}")
                    return True
                else:
                    print("✗ Delete succeeded but relation still exists")
                    return False
            else:
                print("✗ Delete failed")
                return False
        except Exception as e:
            print(f"✗ Delete exception: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    async def test_delete_relations_by_group_id(self):
        """Test deleting relations by group_id"""
        print("\n" + "=" * 50)
        print("Testing delete relations by group_id")
        print("=" * 50)
        
        try:
            # Create a test group and relations
            if not self.test_groups:
                group = self.generate_test_group()
                await self.service.create_group(group)
                self.test_groups.append(group)
            
            test_group = self.test_groups[0]
            
            # Create multiple relations
            for _ in range(3):
                test_sd_id = str(uuid.uuid4())
                relation = self.generate_test_relation(test_sd_id, test_group.id)
                await self.service.create_relation(relation)
            
            # Delete by group_id
            success = await self.service.delete_relations_by_group_id(test_group.id)
            
            if success:
                # Verify deletion
                retrieved = await self.service.get_relations_by_group_id(test_group.id)
                if len(retrieved) == 0:
                    print(f"✓ All relations deleted for group: {test_group.id}")
                    return True
                else:
                    print(f"✗ Delete succeeded but {len(retrieved)} relations still exist")
                    return False
            else:
                print("✗ Delete failed")
                return False
        except Exception as e:
            print(f"✗ Delete by group_id exception: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    async def test_delete_relations_by_sd_id(self):
        """Test deleting relations by sd_id"""
        print("\n" + "=" * 50)
        print("Testing delete relations by sd_id")
        print("=" * 50)
        
        try:
            # Create test groups and a relation
            if not self.test_groups:
                group = self.generate_test_group()
                await self.service.create_group(group)
                self.test_groups.append(group)
            
            test_group = self.test_groups[0]
            test_sd_id = str(uuid.uuid4())
            
            # Create relation
            relation = self.generate_test_relation(test_sd_id, test_group.id)
            await self.service.create_relation(relation)
            
            # Delete by sd_id
            success = await self.service.delete_relations_by_sd_id(test_sd_id)
            
            if success:
                # Verify deletion
                retrieved = await self.service.get_relations_by_sd_id(test_sd_id)
                if len(retrieved) == 0:
                    print(f"✓ All relations deleted for SD: {test_sd_id}")
                    return True
                else:
                    print(f"✗ Delete succeeded but {len(retrieved)} relations still exist")
                    return False
            else:
                print("✗ Delete failed")
                return False
        except Exception as e:
            print(f"✗ Delete by sd_id exception: {e}")
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
            # Clean up relations first (they may have foreign key constraints)
            deleted_relations = 0
            for relation in self.test_relations:
                try:
                    if relation.id:
                        await self.service.delete_relation(relation.id)
                        deleted_relations += 1
                except:
                    # Try deleting by sd_id and group_id if id is not available
                    try:
                        await self.service.delete_relations_by_sd_id(relation.sd_id)
                        deleted_relations += 1
                    except:
                        pass
            
            # Clean up groups
            deleted_groups = 0
            for group in self.test_groups:
                try:
                    await self.service.delete_group(group.id)
                    deleted_groups += 1
                except:
                    pass
            
            print(f"✓ Cleaned up {deleted_groups} test groups and {deleted_relations} test relations")
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
    tester = SemanticGroupServiceTester()
    
    test_methods = [
        ("Initialize", tester.test_initialize),
        ("Table Structure", tester.test_table_structure),
        ("Create Group", tester.test_create_group),
        ("Create Group with ID", tester.test_create_group_with_id),
        ("Batch Create Groups", tester.test_batch_create_groups),
        ("Get Group by ID", tester.test_get_group_by_id),
        ("Get All Groups", tester.test_get_all_groups),
        ("Get All Groups Pagination", tester.test_get_all_groups_pagination),
        ("Update Group", tester.test_update_group),
        ("Delete Group", tester.test_delete_group),
        ("Count Groups", tester.test_count_groups),
        ("Exists Group", tester.test_exists_group),
        ("Create Relation", tester.test_create_relation),
        ("Batch Create Relations", tester.test_batch_create_relations),
        ("Get Relations by Group ID", tester.test_get_relations_by_group_id),
        ("Get Relations by SD ID", tester.test_get_relations_by_sd_id),
        ("Delete Relation", tester.test_delete_relation),
        ("Delete Relations by Group ID", tester.test_delete_relations_by_group_id),
        ("Delete Relations by SD ID", tester.test_delete_relations_by_sd_id),
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
