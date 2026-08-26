"""Celery workers with late acknowledgement and persisted attempt/event recovery."""
import os


def create_celery():
    from celery import Celery
    app = Celery("aux", broker=os.environ["REDIS_URL"], backend=os.environ["REDIS_URL"])
    app.conf.update(task_acks_late=True, task_reject_on_worker_lost=True, worker_prefetch_multiplier=1, broker_transport_options={"visibility_timeout": 3600})
    app.conf.beat_schedule = {"retention-sweep-hourly": {"task": "aux.retention_sweep", "schedule": 3600.0}}
    return app


if os.getenv("REDIS_URL"):
    celery_app = create_celery()

    @celery_app.task(name="aux.execute_job", bind=True, autoretry_for=(ConnectionError,), retry_backoff=True, max_retries=5)
    def execute_job(self, job_id):
        from .executor import JobExecutor
        from .store import create_store
        store = create_store()
        store.event(job_id, "job.worker_received", None, {"celery_task_id": self.request.id})
        JobExecutor(store).run(job_id)
        return store.get_job(job_id)["status"]

    @celery_app.task(name="aux.retention_sweep", bind=True, autoretry_for=(ConnectionError,), retry_backoff=True, max_retries=5)
    def retention_sweep(self):
        from .store import create_store
        return create_store().delete_expired_artifacts()
else:
    celery_app = None
