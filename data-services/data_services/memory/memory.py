import os
import logging
from typing import List, Dict, Any, Optional
from mem0 import Memory
from mem0 import AsyncMemory
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class MemoryService:
    def __init__(self):
        self.memory_instance = None
        self.memory_config = None
    
    def initialize(self, config: Dict[str, Any]):
        self.memory_config = config
        self.memory_instance = Memory.from_config(self.memory_config)
        logger.info("Memory service initialized successfully")

    def add_memory(self, messages: List[Dict[str, str]], user_id: Optional[str] = None, agent_id: Optional[str] = None, 
        run_id: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not self.memory_instance:
            raise ValueError("Memory service not initialized. Call initialize() first.")
        logger.info(
            f"Adding memory - user_id: {user_id}, agent_id: {agent_id}, run_id: {run_id}, "
            f"message_count: {len(messages)}, metadata_keys: {list(metadata.keys()) if metadata else 'None'}"
        )
        return self.memory_instance.add(messages, user_id=user_id, agent_id=agent_id, run_id=run_id, metadata=metadata or {})
    
    def get_memory(self, memory_id: str) -> Dict[str, Any]:
        if not self.memory_instance:
            raise ValueError("Memory service not initialized. Call initialize() first.")
        
        return self.memory_instance.get(memory_id)
    
    def get_all_memories(self, user_id: Optional[str] = None, agent_id: Optional[str] = None, run_id: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None, limit: int = 100) -> List[Dict[str, Any]]:
        if not self.memory_instance:
            raise ValueError("Memory service not initialized. Call initialize() first.")
        
        result = self.memory_instance.get_all(user_id=user_id, agent_id=agent_id, run_id=run_id, filters=filters, limit=limit)
        return result.get("results", [])
    
    def search_memories(self, query: str, user_id: Optional[str] = None, agent_id: Optional[str] = None, run_id: Optional[str] = None, 
        filters: Optional[Dict[str, Any]] = None, limit: int = 100, threshold: Optional[float] = None) -> List[Dict[str, Any]]:
        if not self.memory_instance:
            raise ValueError("Memory service not initialized. Call initialize() first.")
        
        return self.memory_instance.search(query, user_id=user_id, agent_id=agent_id, run_id=run_id, filters=filters, limit=limit, threshold=threshold)
    
    def update_memory(self, memory_id: str, data: str) -> Dict[str, Any]:
        if not self.memory_instance:
            raise ValueError("Memory service not initialized. Call initialize() first.")
        
        return self.memory_instance.update(memory_id, data)

    def delete_memory(self, memory_id: str) -> Dict[str, Any]:
        if not self.memory_instance:
            raise ValueError("Memory service not initialized. Call initialize() first.")
        
        return self.memory_instance.delete(memory_id)
    
    def delete_all_memories(self, user_id: Optional[str] = None, agent_id: Optional[str] = None, run_id: Optional[str] = None) -> Dict[str, str]:
        if not self.memory_instance:
            raise ValueError("Memory service not initialized. Call initialize() first.")
        
        return self.memory_instance.delete_all(user_id=user_id, agent_id=agent_id, run_id=run_id)
    
    def get_memory_history(self, memory_id: str) -> List[Dict[str, Any]]:
        if not self.memory_instance:
            raise ValueError("Memory service not initialized. Call initialize() first.")
        
        return self.memory_instance.history(memory_id)
    
    def reset_all(self) -> Dict[str, str]:
        if not self.memory_instance:
            raise ValueError("Memory service not initialized. Call initialize() first.")
        
        return self.memory_instance.reset()


class AsyncMemoryService:
    def __init__(self):
        self.memory_instance = None
        self.memory_config = None
    
    async def initialize(self, config: Dict[str, Any]):
        self.memory_config = config
        
        try:
            self.memory_instance = await AsyncMemory.from_config(self.memory_config)
            logger.info("Memory service initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize services: {str(e)}")
            raise

    async def add_memory(self, messages: List[Dict[str, str]], user_id: Optional[str] = None, agent_id: Optional[str] = None, 
        run_id: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not self.memory_instance:
            raise ValueError("Async Memory service not initialized. Call initialize() first.")
        logger.info(
            f"Adding memory - user_id: {user_id}, agent_id: {agent_id}, run_id: {run_id}, "
            f"message_count: {len(messages)}, metadata_keys: {list(metadata.keys()) if metadata else 'None'}"
        )
        return await self.memory_instance.add(messages, user_id=user_id, agent_id=agent_id, run_id=run_id, metadata=metadata or {})
    
    async def get_memory(self, memory_id: str) -> Dict[str, Any]:
        if not self.memory_instance:
            raise ValueError("Async Memory service not initialized. Call initialize() first.")
        
        return await self.memory_instance.get(memory_id)
    
    async def get_all_memories(self, user_id: Optional[str] = None, agent_id: Optional[str] = None, run_id: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None, limit: int = 100) -> List[Dict[str, Any]]:
        if not self.memory_instance:
            raise ValueError("Async Memory service not initialized. Call initialize() first.")
        
        result = await self.memory_instance.get_all(user_id=user_id, agent_id=agent_id, run_id=run_id, filters=filters, limit=limit)
        return result.get("results", [])
    
    async def search_memories(self, query: str, user_id: Optional[str] = None, agent_id: Optional[str] = None, run_id: Optional[str] = None, 
        filters: Optional[Dict[str, Any]] = None, limit: int = 100, threshold: Optional[float] = None) -> List[Dict[str, Any]]:
        if not self.memory_instance:
            raise ValueError("Async Memory service not initialized. Call initialize() first.")
        
        return await self.memory_instance.search(query, user_id=user_id, agent_id=agent_id, run_id=run_id, filters=filters, limit=limit, threshold=threshold)
    
    async def update_memory(self, memory_id: str, data: str) -> Dict[str, Any]:
        if not self.memory_instance:
            raise ValueError("Async Memory service not initialized. Call initialize() first.")
        
        return await self.memory_instance.update(memory_id, data)

    async def delete_memory(self, memory_id: str) -> Dict[str, Any]:
        if not self.memory_instance:
            raise ValueError("Async Memory service not initialized. Call initialize() first.")
        
        return await self.memory_instance.delete(memory_id)
    
    async def delete_all_memories(self, user_id: Optional[str] = None, agent_id: Optional[str] = None, run_id: Optional[str] = None) -> Dict[str, str]:
        if not self.memory_instance:
            raise ValueError("Async Memory service not initialized. Call initialize() first.")
        
        return await self.memory_instance.delete_all(user_id=user_id, agent_id=agent_id, run_id=run_id)
    
    async def get_memory_history(self, memory_id: str) -> List[Dict[str, Any]]:
        if not self.memory_instance:
            raise ValueError("Async Memory service not initialized. Call initialize() first.")
        
        return await self.memory_instance.history(memory_id)
    
    async def reset_all(self) -> Dict[str, str]:
        if not self.memory_instance:
            raise ValueError("Async Memory service not initialized. Call initialize() first.")
        
        return await self.memory_instance.reset()
