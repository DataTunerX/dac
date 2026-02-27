"""
Simple API service to check the job execution status file (/app/status/status.json).
"""
import json
import os
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

app = FastAPI(
    title="Data Sinkers Status API",
    description="API to check job execution status from /app/status/status.json",
    version="0.1.0",
)

# Status file path (same as in job.py)
DEFAULT_STATUS_FILE = "/app/status/status.json"


def get_status_file_path() -> str:
    """Get status file path from env or default."""
    return os.getenv("STATUS_FILE", DEFAULT_STATUS_FILE)


def read_status_file() -> Dict[str, Any]:
    """
    Read and parse the status file.
    Returns the content as dict. When file does not exist (job not run yet),
    returns a pending payload so the controller can retry instead of treating 404 as error.
    Raises HTTPException only on real errors (permission, invalid JSON, etc.).
    """
    path = get_status_file_path()
    if not os.path.exists(path):
        return {
            "status": "pending",
            "task_id": None,
            "timestamp": None,
            "error": "",
            "message": "Job may not have run yet or status file is not mounted.",
        }
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data
    except (PermissionError, OSError) as e:
        hint = (
            "Ensure job and status containers share the same volume for /app/status, "
            "and that the job has written the file with readable permissions (e.g. chmod 0o644)."
        )
        raise HTTPException(
            status_code=503,
            detail={
                "error": "Permission denied reading status file",
                "path": path,
                "message": str(e),
                "hint": hint,
            },
        )
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=500,
            detail={
                "error": "Invalid JSON in status file",
                "path": path,
                "message": str(e),
            },
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={
                "error": "Failed to read status file",
                "path": path,
                "message": str(e),
            },
        )


@app.get("/status", response_class=JSONResponse)
def get_status() -> Dict[str, Any]:
    """
    Get the current job execution status.
    Returns the full content of the status file (status, task_id, timestamp, result/error).
    """
    return read_status_file()


@app.get("/status/summary")
def get_status_summary() -> Dict[str, Any]:
    """
    Get a brief summary: status, task_id, timestamp, and success/failure indicator.
    """
    data = read_status_file()
    return {
        "status": data.get("status", "unknown"),
        "task_id": data.get("task_id"),
        "timestamp": data.get("timestamp"),
        "success": data.get("status") == "success",
    }


@app.get("/health")
def health() -> Dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok", "service": "data-sinkers-status"}


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
