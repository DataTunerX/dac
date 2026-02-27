import logging
import json
from typing import Union, Dict, Any, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from celery.result import AsyncResult

from semantic_grouper.celery_app import celery, semantic_group_task

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("semantic_grouper.server")

app = FastAPI(title="semantic-grouper", version="0.1.0")


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------
class DescriptorModel(BaseModel):
    namespace: str
    name: str


class GroupRequest(BaseModel):
    operation: str  # "AddOrUpdate" or "Delete"
    descriptor: DescriptorModel


class GroupResponse(BaseModel):
    task_id: str


class TaskStatusResponse(BaseModel):
    task_id: str
    status: str
    result: Optional[Union[str, Dict[str, Any]]] = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.post("/api/v1/group", response_model=GroupResponse)
async def group(request: GroupRequest):
    """
    Submit a semantic grouping request.
    Returns a task_id immediately; the caller should poll /api/v1/task_status/{task_id}.
    """
    if request.operation not in ("AddOrUpdate", "Delete"):
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported operation: {request.operation}. Must be 'AddOrUpdate' or 'Delete'.",
        )

    task_data = {
        "operation": request.operation,
        "descriptor": {
            "namespace": request.descriptor.namespace,
            "name": request.descriptor.name,
        },
    }

    logger.info("Dispatching semantic group task: %s", task_data)
    result = semantic_group_task.delay(task_data)
    return {"task_id": result.id}


@app.get("/api/v1/task_status/{task_id}", response_model=TaskStatusResponse)
async def task_status(task_id: str):
    """
    Poll the status of a semantic grouping task.

    Possible statuses: PENDING, STARTED, SUCCESS, FAILURE, RETRY, REVOKED.
    """
    task_result = AsyncResult(task_id, app=celery)

    result = None
    if task_result.ready():
        if task_result.successful():
            result = task_result.result
        else:
            result = {
                "error": str(task_result.result),
                "traceback": task_result.traceback,
            }

    return {
        "task_id": task_id,
        "status": task_result.status,
        "result": result,
    }


@app.get("/")
async def root():
    return {"status": "running", "service": "semantic-grouper"}


@app.get("/info")
async def info():
    return {
        "service": "semantic-grouper",
        "version": "0.1.0",
    }
