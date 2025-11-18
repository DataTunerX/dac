import json
import logging
import os
from fastapi import FastAPI, HTTPException
from typing import Union, Dict, Any
import click
import httpx
import uvicorn
import sys
from pydantic import BaseModel
from celery import Celery
from celery.result import AsyncResult
from urllib.parse import quote_plus

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

app = FastAPI(title="celery httpserver", version="0.1.0")

redis_host = os.getenv('REDIS_HOST', 'localhost')
redis_port = os.getenv('REDIS_PORT', '6379')
redis_db_broker = os.getenv('REDIS_DB_BROKER', '0')
redis_db_backend = os.getenv('REDIS_DB_BACKEND', '1')
redis_password = os.getenv('REDIS_PASSWORD')

logger.info("\n=== Redis Configuration ===")
logger.info(f"REDIS_HOST: {redis_host}")
logger.info(f"REDIS_PORT: {redis_port}")
logger.info(f"REDIS_DB_BROKER: {redis_db_broker}")
logger.info(f"REDIS_DB_BACKEND: {redis_db_backend}")
logger.info(f"REDIS_PASSWORD: {'****' if redis_password else '<empty>'}")

# URL encode the password if it contains special characters
password_part = f':{quote_plus(redis_password)}@' if redis_password else ''
broker_url = f'redis://{password_part}{redis_host}:{redis_port}/{redis_db_broker}'
backend_url = f'redis://{password_part}{redis_host}:{redis_port}/{redis_db_backend}'

logger.info(f"Constructed broker URL: {broker_url}")
logger.info(f"Constructed backend URL: {backend_url}")


# Test Redis connection
try:
    import redis
    r = redis.Redis(
        host=redis_host,
        port=int(redis_port),
        db=int(redis_db_broker),
        password=redis_password or None,
        socket_timeout=5
    )
    logger.info("Redis connection test: PING -> %s", r.ping())
except Exception as e:
    logger.error("Redis connection test failed: %s", str(e))


celery = Celery(
    'tasks',
    broker=broker_url,
    backend=backend_url
)

celery.conf.task_default_queue = 'dataset'
celery.conf.task_routes = {
    'tasks.process_data': {'queue': 'dataset'},
}
celery.conf.task_create_missing_queues = False

# Log Celery configuration
logger.info("\n=== Celery Configuration ===")
logger.info(f"Broker URL: {celery.conf.broker_url}")
logger.info(f"Backend URL: {celery.conf.result_backend}")
logger.info(f"Default queue: {celery.conf.task_default_queue}")
logger.info(f"Task routes: {celery.conf.task_routes}")
logger.info("Celery initialized successfully\n")

class TaskRequest(BaseModel):
    data: dict

class TaskResponse(BaseModel):
    task_id: str

class TaskStatusResponse(BaseModel):
    task_id: str
    status: str
    result: Union[str, Dict[str, Any], None] = None


@app.post("/trigger_task", response_model=TaskResponse)
async def trigger_task(request: TaskRequest):

    if not request.data:
        logger.warning("=====Received empty data in request")
        raise HTTPException(status_code=400, detail="Data cannot be empty")

    logger.info(f"=====Task request data: {request.data}")
    logger.info(f"=====Data keys: {list(request.data.keys())}")

    try:
        result = celery.send_task(
            'tasks.process_data', 
            args=[request.data],
            queue='dataset'
        )
        return {"task_id": result.id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/task_status/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(task_id: str):
    task_result = AsyncResult(task_id, app=celery)
    
    result = None
    if task_result.ready():
        if task_result.successful():
            result = task_result.result
        else:
            result = {
                "error": str(task_result.result),
                "traceback": task_result.traceback
            }
    
    return {
        "task_id": task_id,
        "status": task_result.status,
        "result": result
    }

@app.get("/")
async def root():
    return {"status": "running"}

@app.get("/info")
async def get_info():
    return {
        "service": "celery-httpserver",
        "version": "0.1.0"
    }

@click.command()
@click.option('--host', default='0.0.0.0', help='Host to bind')
@click.option('--port', default=8000, help='Port to bind')
def main(host, port):
    logging.basicConfig(
        force=True,
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler()]
    )

    try:        
        logger.info(f"Starting server on {host}:{port}")

        uvicorn.run(
            app,
            host=host,
            port=port
        )

    except json.JSONDecodeError:
        logger.error(f"Error: File '{agent_card}' contains invalid JSON.")
        sys.exit(1)
    except Exception as e:
        logger.error(f'An error occurred during server startup: {e}')
        sys.exit(1)

if __name__ == '__main__':
    main()