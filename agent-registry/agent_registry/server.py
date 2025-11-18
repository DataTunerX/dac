import json
import os
import logging
from pathlib import Path
import numpy as np
import pandas as pd
import requests
from datetime import datetime
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.utilities.logging import get_logger
import click
from .redis_registry import RedisRegistry, CleanupService
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from typing import List, Optional
from pydantic import BaseModel
from a2a.types import AgentCard
from .vector_client import SearchResult, VectorClient, Document, serialize_object
import asyncio
from typing import Any, Dict

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)

logger = logging.getLogger(__name__)

collection_name = os.getenv('COLLECTION_NAME', 'agent_cards')

class AgentListResponse(BaseModel):
    agent_cards: List[AgentCard]

class SearchRequest(BaseModel):
    query: str
    collection: str
    search_type: str = "vector"  # vector, fulltext, hybrid
    limit: int = 10
    hybrid_threshold: float = 0.1
    fulltext_weight: Optional[float] = 0.5
    vector_weight: Optional[float] = 0.5

def create_vector_client():
    data_services_url = os.getenv('DATA_SERVICES', 'http://data-services.dac.svc.cluster.local:8000')
    return VectorClient(base_url=data_services_url)

def add_agent_to_vector_db(agent_url: str, agent: AgentCard):
    try:
        vector_client = create_vector_client()
        
        agent_content = f"""
        Agent Name: {agent.name}
        Description: {agent.description}
        URL: {agent_url}
        """

        document = Document(
            page_content=agent_content,
            metadata={
                "agent": serialize_object(agent),
                "agent_url": agent_url
            }
        )

        result = vector_client.add_documents(
            collection_name=collection_name,
            documents=[document]
        )
        
        logger.info(f"Successfully added agent '{agent.name}' to vector database")
        return result
        
    except Exception as e:
        logger.error(f"Failed to add agent '{agent.name}' to vector database: {e}")
        return None

def remove_agent_from_vector_db(agent_url: str, agent: AgentCard):
    try:
        vector_client = create_vector_client()

        result = vector_client.delete_by_metadata_field(
            collection_name=collection_name,
            key="agent_url",
            value=agent_url
        )
        
        logger.info(f"Successfully deleted agent {agent_url} from vector database")
        return result
        
    except Exception as e:
        logger.error(f"Failed to delete agent {agent_url} from vector database: {e}")
        return None

def change_logger(event_type, agent_url, agent):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    if event_type == "add":
        logger.info(f"[{timestamp}] ADDED Agent: {agent_url}, Details: {agent.name} | Description: {agent.description}")
        add_agent_to_vector_db(agent_url, agent)
    elif event_type == "remove":
        logger.info(f"[{timestamp}] REMOVED Agent: {agent_url}")
        remove_agent_from_vector_db(agent_url, agent)


def create_fastapi_app(registry):
    """Create FastAPI application with routes"""
    app = FastAPI(title="Agent Cards API", version="1.0.0")

    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/")
    async def root():
        return {"message": "Agent Cards API", "status": "running"}

    @app.get("/agents", response_model=AgentListResponse)
    async def get_agents():
        """Get all agents"""
        try:
            agents = registry.get_agents()
            return {"agent_cards": agents}
        except Exception as e:
            logger.error(f"Error getting agents: {e}")
            raise HTTPException(status_code=500, detail="Internal server error")

    @app.post("/search", response_model=SearchResult)
    async def search_documents(request: SearchRequest):
        try:
            data_services_url = os.getenv('DATA_SERVICES', 'http://data-services.dac.svc.cluster.local:8000')

            vector_client = VectorClient(base_url=data_services_url)

            search_response = await vector_client.avector_search(request.collection, request.query, limit=10)

            return search_response
        except Exception as e:
            logger.error(f"Search error: {e}")
            raise HTTPException(status_code=500, detail="Search failed")

    return app

def serve_mcp(host, port, transport, redis_host, redis_port, redis_db, password):
    """Initializes and runs the Agent Cards MCP server."""
    
    logger.info('Starting Agent Cards MCP Server')

    registry = RedisRegistry(host=redis_host, port=redis_port, db=redis_db, password=password)

    logger.info('Starting CleanupService')
    cleanup_service = CleanupService(registry)
    cleanup_service.start()

    logger.info('Starting watch redis changes')
    watcher = registry.watch_changes(change_logger)
    logger.info(f"The watcher thread is active.: {watcher.is_alive()}")

    mcp = FastMCP('agent-cards', host=host, port=port)

    @mcp.resource('resource://agent_cards/list', mime_type='application/json')
    def list_agent_cards() -> dict:
        """Retrieves all loaded agent cards as a json / dictionary for the MCP resource endpoint."""
        agents = registry.get_agents()
        card_uris = [f'resource://agent_cards/{agent.name}' for agent in agents]
        return {"agent_cards": card_uris}

    @mcp.resource('resource://agent_cards/{card_name}', mime_type='application/json')
    def get_agent_card(card_name: str) -> dict:
        """Retrieves an agent card as a json / dictionary for the MCP resource endpoint."""
        agents = registry.get_agents()
        agent = next((a for a in agents if a.name == card_name), None)
        return {"agent_card": agent} if agent else {}

    @mcp.resource('resource://agent_cards/agents', mime_type='application/json')
    def get_agent_cards() -> dict:
        """Retrieves all loaded agent cards as a json / dictionary for the MCP resource endpoint."""
        agents = registry.get_agents()
        return {"agent_cards": agents}

    logger.info(f'Agent cards MCP Server at {host}:{port} and transport {transport}')
    mcp.run(transport=transport)


def serve_api(host, port, redis_host, redis_port, redis_db, password):
    """Initializes and runs the FastAPI server."""
    
    logger.info('Starting Agent Cards FastAPI Server')

    registry = RedisRegistry(host=redis_host, port=redis_port, db=redis_db, password=password)

    logger.info('Starting CleanupService')
    cleanup_service = CleanupService(registry)
    cleanup_service.start()

    logger.info('Starting watch redis changes')
    watcher = registry.watch_changes(change_logger)
    logger.info(f"The watcher thread is active.: {watcher.is_alive()}")

    app = create_fastapi_app(registry)

    logger.info(f'Agent cards FastAPI Server at {host}:{port}')
    uvicorn.run(app, host=host.split('//')[-1] if '//' in host else host, port=port)


def serve_both(mcp_host, mcp_port, mcp_transport, api_host, api_port, redis_host, redis_port, redis_db, password):
    """Run both MCP server and FastAPI server concurrently."""
    import threading
    
    logger.info('Starting both MCP and FastAPI servers')
    
    registry = RedisRegistry(host=redis_host, port=redis_port, db=redis_db, password=password)

    logger.info('Starting CleanupService')
    cleanup_service = CleanupService(registry)
    cleanup_service.start()

    logger.info('Starting watch redis changes')
    watcher = registry.watch_changes(change_logger)
    logger.info(f"The watcher thread is active.: {watcher.is_alive()}")

    # Start MCP server in a separate thread
    def run_mcp():
        serve_mcp(mcp_host, mcp_port, mcp_transport, redis_host, redis_port, redis_db, password)

    # Start FastAPI server in a separate thread  
    def run_api():
        serve_api(api_host, api_port, redis_host, redis_port, redis_db, password)

    mcp_thread = threading.Thread(target=run_mcp, daemon=True)
    api_thread = threading.Thread(target=run_api, daemon=True)

    mcp_thread.start()
    api_thread.start()

    logger.info(f'MCP Server running at {mcp_host}:{mcp_port}')
    logger.info(f'FastAPI Server running at {api_host}:{api_port}')
    logger.info('Both servers are running...')

    try:
        # Keep main thread alive
        while True:
            import time
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutting down servers...")


@click.command()
@click.option('--run', 'command', default='api-server', help='Command to run: mcp-server, api-server, or both')
@click.option(
    '--host',
    'host',
    default='0.0.0.0',
    help='Host on which the server is started',
)
@click.option(
    '--port',
    'port',
    default=10100,
    help='Port on which the server is started',
)
@click.option(
    '--transport',
    'transport',
    default='sse',
    help='MCP Transport',
)
@click.option('--redis-host', 'redis_host', default='localhost', help='Redis server host')
@click.option('--redis-port', 'redis_port', default=6379, type=int)
@click.option('--redis-db', 'redis_db', default=0, type=int)
@click.option('--password', 'password', default=None)
@click.option('--api-host', 'api_host', default='0.0.0.0', help='FastAPI server host')
@click.option('--api-port', 'api_port', default=8000, help='FastAPI server port')
def main(command, host, port, transport, redis_host, redis_port, redis_db, password, api_host, api_port) -> None:
    
    try:
        vector_client = create_vector_client()

        result = vector_client.create_collection(
            collection_name=collection_name
        )
        
        print(f"Successfully create collection {collection_name}, result = {result}")

    except Exception as e:
        raise ValueError(f'Failed to create collection when start agentregistry: {collection_name}')

    print(f"Starting {command}")
    
    if command == 'mcp-server':
        serve_mcp(host, port, transport, redis_host, redis_port, redis_db, password)
    elif command == 'api-server':
        serve_api(api_host, api_port, redis_host, redis_port, redis_db, password)
    elif command == 'both':
        serve_both(host, port, transport, api_host, api_port, redis_host, redis_port, redis_db, password)
    else:
        raise ValueError(f'Unknown run option: {command}')


if __name__ == "__main__":
    main()