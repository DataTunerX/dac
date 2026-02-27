#!/bin/bash

set -e

exec celery -A semantic_grouper.celery_app beat \
  -S redbeat.RedBeatScheduler \
  --loglevel ${LOG_LEVEL:-INFO}
