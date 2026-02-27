#!/bin/bash

set -e

CONCURRENCY_OPTION="-c ${CELERY_WORKER_AMOUNT:-2}"

exec celery -A semantic_grouper.celery_app worker -P ${CELERY_WORKER_CLASS:-gevent} $CONCURRENCY_OPTION \
  --max-tasks-per-child ${MAX_TASKS_PER_CHILD:-50} --loglevel ${LOG_LEVEL:-INFO} \
  -Q ${CELERY_QUEUES:-semantic_group}
