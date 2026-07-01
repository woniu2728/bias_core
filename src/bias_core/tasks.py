from __future__ import annotations

import os

from celery import shared_task


@shared_task(name="bias_core.queue_worker_probe")
def queue_worker_probe(token: str) -> dict:
    return {
        "ok": True,
        "token": str(token),
        "worker_pid": os.getpid(),
    }
