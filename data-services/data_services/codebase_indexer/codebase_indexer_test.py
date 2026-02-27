import asyncio
import pytest
import pytest_asyncio
import uuid
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from data_services.codebase_indexer.codebase_indexer import AsyncCodebaseIndexerService
from data_services.api.base import CodebaseIndexer


class TestAsyncCodebaseIndexerService:
    """Test cases for AsyncCodebaseIndexerService"""
    
    @pytest_asyncio.fixture
    async def service(self):
        """Create and initialize service instance"""
        service = AsyncCodebaseIndexerService()
        await service.initialize()
        yield service
        await service.close()
    
    @pytest.fixture
    def sample_codebase_indexer(self):
        """Create a sample CodebaseIndexer for testing"""
        return CodebaseIndexer(
            codebase_indexer_id=str(uuid.uuid4()),
            filepath="/src/test/example.py",
            code_deep_analysis="This is a test file containing utility functions for data processing.",
            dd_namespace="test_namespace",
            dd_name="test_dd"
        )
    
    @pytest.fixture
    def sample_codebase_indexers(self):
        """Create multiple sample CodebaseIndexers for batch testing"""
        return [
            CodebaseIndexer(
                codebase_indexer_id=str(uuid.uuid4()),
                filepath=f"/src/test/file_{i}.py",
                code_deep_analysis=f"Analysis for file {i}",
                dd_namespace="batch_namespace",
                dd_name="batch_dd"
            )
            for i in range(3)
        ]

    @pytest.mark.asyncio
    async def test_initialize(self, service):
        """Test service initialization"""
        assert service.pool is not None
        status = await service.get_connection_pool_status()
        assert status['pool_initialized'] is True
    
    @pytest.mark.asyncio
    async def test_create_and_get_by_id(self, service, sample_codebase_indexer):
        """Test create and get_by_id"""
        # Create record
        result = await service.create(sample_codebase_indexer)
        assert result is True
        
        # Get by ID
        record = await service.get_by_id(sample_codebase_indexer.codebase_indexer_id)
        assert record is not None
        assert record.codebase_indexer_id == sample_codebase_indexer.codebase_indexer_id
        assert record.filepath == sample_codebase_indexer.filepath
        assert record.code_deep_analysis == sample_codebase_indexer.code_deep_analysis
        assert record.dd_namespace == sample_codebase_indexer.dd_namespace
        assert record.dd_name == sample_codebase_indexer.dd_name
        
        # Cleanup
        await service.delete(sample_codebase_indexer.codebase_indexer_id)
    
    @pytest.mark.asyncio
    async def test_create_auto_generate_id(self, service):
        """Test create with auto-generated ID"""
        record = CodebaseIndexer(
            filepath="/src/auto_id_test.py",
            code_deep_analysis="Test auto ID generation",
            dd_namespace="auto_ns",
            dd_name="auto_dd"
        )
        
        result = await service.create(record)
        assert result is True
        assert record.codebase_indexer_id is not None
        
        # Cleanup
        await service.delete(record.codebase_indexer_id)
    
    @pytest.mark.asyncio
    async def test_batch_create(self, service, sample_codebase_indexers):
        """Test batch create"""
        result = await service.batch_create(sample_codebase_indexers)
        assert result is True
        
        # Verify all records were created
        for record in sample_codebase_indexers:
            fetched = await service.get_by_id(record.codebase_indexer_id)
            assert fetched is not None
            assert fetched.filepath == record.filepath
        
        # Cleanup
        await service.delete_by_dd_info("batch_namespace", "batch_dd")
    
    @pytest.mark.asyncio
    async def test_get_by_dd_info(self, service, sample_codebase_indexers):
        """Test get_by_dd_info"""
        # Create batch records
        await service.batch_create(sample_codebase_indexers)
        
        # Get by DD info
        records = await service.get_by_dd_info("batch_namespace", "batch_dd")
        assert len(records) == 3
        
        # Cleanup
        await service.delete_by_dd_info("batch_namespace", "batch_dd")
    
    @pytest.mark.asyncio
    async def test_get_all_with_pagination(self, service, sample_codebase_indexers):
        """Test get_all with pagination"""
        # Create batch records
        await service.batch_create(sample_codebase_indexers)
        
        # Get all without pagination
        all_records = await service.get_all()
        assert len(all_records) >= 3
        
        # Get with pagination
        page1 = await service.get_all(page=1, page_size=2)
        assert len(page1) <= 2
        
        # Cleanup
        await service.delete_by_dd_info("batch_namespace", "batch_dd")
    
    @pytest.mark.asyncio
    async def test_update(self, service, sample_codebase_indexer):
        """Test update"""
        # Create record
        await service.create(sample_codebase_indexer)
        
        # Update record
        update_data = CodebaseIndexer(
            filepath="/src/updated/path.py",
            code_deep_analysis="Updated analysis content"
        )
        result = await service.update(sample_codebase_indexer.codebase_indexer_id, update_data)
        assert result is True
        
        # Verify update
        record = await service.get_by_id(sample_codebase_indexer.codebase_indexer_id)
        assert record.filepath == "/src/updated/path.py"
        assert record.code_deep_analysis == "Updated analysis content"
        
        # Cleanup
        await service.delete(sample_codebase_indexer.codebase_indexer_id)
    
    @pytest.mark.asyncio
    async def test_delete(self, service, sample_codebase_indexer):
        """Test delete"""
        # Create record
        await service.create(sample_codebase_indexer)
        
        # Verify exists
        assert await service.exists(sample_codebase_indexer.codebase_indexer_id) is True
        
        # Delete
        result = await service.delete(sample_codebase_indexer.codebase_indexer_id)
        assert result is True
        
        # Verify deleted
        assert await service.exists(sample_codebase_indexer.codebase_indexer_id) is False
    
    @pytest.mark.asyncio
    async def test_delete_by_dd_info(self, service, sample_codebase_indexers):
        """Test delete_by_dd_info"""
        # Create batch records
        await service.batch_create(sample_codebase_indexers)
        
        # Verify exists
        assert await service.exists_by_dd_info("batch_namespace", "batch_dd") is True
        
        # Delete by DD info
        result = await service.delete_by_dd_info("batch_namespace", "batch_dd")
        assert result is True
        
        # Verify deleted
        assert await service.exists_by_dd_info("batch_namespace", "batch_dd") is False
    
    @pytest.mark.asyncio
    async def test_count(self, service, sample_codebase_indexers):
        """Test count"""
        # Get initial count
        initial_count = await service.count()
        
        # Create batch records
        await service.batch_create(sample_codebase_indexers)
        
        # Verify count increased
        new_count = await service.count()
        assert new_count == initial_count + 3
        
        # Test count with condition
        condition_count = await service.count(
            "dd_namespace = %s AND dd_name = %s", 
            ("batch_namespace", "batch_dd")
        )
        assert condition_count == 3
        
        # Cleanup
        await service.delete_by_dd_info("batch_namespace", "batch_dd")
    
    @pytest.mark.asyncio
    async def test_exists(self, service, sample_codebase_indexer):
        """Test exists"""
        # Should not exist initially
        assert await service.exists(sample_codebase_indexer.codebase_indexer_id) is False
        
        # Create record
        await service.create(sample_codebase_indexer)
        
        # Should exist now
        assert await service.exists(sample_codebase_indexer.codebase_indexer_id) is True
        
        # Cleanup
        await service.delete(sample_codebase_indexer.codebase_indexer_id)
    
    @pytest.mark.asyncio
    async def test_exists_by_dd_info(self, service, sample_codebase_indexer):
        """Test exists_by_dd_info"""
        # Should not exist initially
        assert await service.exists_by_dd_info(
            sample_codebase_indexer.dd_namespace, 
            sample_codebase_indexer.dd_name
        ) is False
        
        # Create record
        await service.create(sample_codebase_indexer)
        
        # Should exist now
        assert await service.exists_by_dd_info(
            sample_codebase_indexer.dd_namespace, 
            sample_codebase_indexer.dd_name
        ) is True
        
        # Cleanup
        await service.delete(sample_codebase_indexer.codebase_indexer_id)
    
    @pytest.mark.asyncio
    async def test_get_by_id_not_found(self, service):
        """Test get_by_id returns None for non-existent ID"""
        record = await service.get_by_id("non_existent_id_12345")
        assert record is None
    
    @pytest.mark.asyncio
    async def test_get_connection_pool_status(self, service):
        """Test get_connection_pool_status"""
        status = await service.get_connection_pool_status()
        assert 'pool_initialized' in status
        assert status['pool_initialized'] is True
        assert 'minsize' in status
        assert 'maxsize' in status
        assert 'database' in status
        assert 'host' in status


# Run tests directly
if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
