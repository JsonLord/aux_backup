"""Durable job-dispatch boundary."""
from __future__ import annotations

import os


class LocalJobQueue:
    backend = "local"
    def __init__(self, executor, background_tasks): self.executor, self.background_tasks = executor, background_tasks
    def enqueue(self, job_id): self.background_tasks.add_task(self.executor.run, job_id)


class CeleryJobQueue:
    backend = "celery"
    def __init__(self, celery_app): self.celery_app = celery_app
    def enqueue(self, job_id): self.celery_app.send_task("aux.execute_job", args=[job_id], queue="jobs")


def job_queue(executor, background_tasks):
    if os.getenv("JOB_QUEUE", "local") == "celery":
        from .tasks import celery_app
        if celery_app is None: raise RuntimeError("JOB_QUEUE=celery requires REDIS_URL")
        return CeleryJobQueue(celery_app)
    return LocalJobQueue(executor, background_tasks)
