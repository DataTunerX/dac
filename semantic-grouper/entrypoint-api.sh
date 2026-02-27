#!/bin/bash

set -e

exec uvicorn semantic_grouper.server:app --host 0.0.0.0 --port ${API_PORT:-8000} --log-level ${LOG_LEVEL:-info}
