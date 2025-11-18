#!/bin/bash

set -e

CONCURRENCY_OPTION="-c ${CELERY_WORKER_AMOUNT:-10}"

exec celery -A data_sinkers.tasks worker -P ${CELERY_WORKER_CLASS:-gevent} $CONCURRENCY_OPTION \
  --max-tasks-per-child ${MAX_TASKS_PRE_CHILD:-50} --loglevel ${LOG_LEVEL:-INFO} \
  -Q ${CELERY_QUEUES:-dataset}