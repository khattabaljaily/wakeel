"""Pick up queued jobs and run them, one at a time.

The loop runs either as `manage.py run_worker` (production) or, in local
development, as a thread inside `runserver` (see JobsConfig.ready). A lock
file makes sure only one of them works at a time, and a heartbeat file lets
the web pages tell whether any worker is alive.
"""
import fcntl
import logging
import os
import threading
import time

from django.conf import settings
from django.db import close_old_connections, transaction
from django.utils import timezone

from apps.ai.client import AIError
from apps.content import services
from apps.social import services as social

from .models import Job

logger = logging.getLogger(__name__)

HANDLERS = {
    Job.Kind.GENERATE_PLAN: services.run_generate_plan,
    Job.Kind.REWRITE_POST: services.run_rewrite_post,
    Job.Kind.RENDER_POST: services.run_render_post,
    Job.Kind.RENDER_PLAN: services.run_render_plan,
    Job.Kind.PUBLISH_POST: social.run_publish_post,
}


def claim_next():
    with transaction.atomic():
        job = (Job.objects.select_for_update(skip_locked=True)
               .filter(status=Job.Status.PENDING).order_by('created_at').first())
        if job is None:
            return None
        job.status = Job.Status.RUNNING
        job.started_at = timezone.now()
        job.save(update_fields=['status', 'started_at'])
        return job


def run_job(job):
    try:
        message = HANDLERS[job.kind](job)
        if job.was_cancelled():
            job.status = Job.Status.CANCELLED
            return job
    except (AIError, social.PublishError) as exc:  # messages written for the user
        job.status, job.error = Job.Status.FAILED, str(exc)
    except Exception as exc:  # the worker must survive any single job
        logger.exception('Job %s failed', job.pk)
        job.status, job.error = Job.Status.FAILED, f'حدث خطأ غير متوقع: {exc}'
    else:
        job.status, job.progress, job.message = Job.Status.DONE, 100, (message or '')[:255]
    if job.was_cancelled():  # cancelled while running: keep it that way
        job.status = Job.Status.CANCELLED
        return job
    job.finished_at = timezone.now()
    job.save()
    return job


def recover_stale():
    """Jobs left 'running' by a worker that died are re-queued on startup."""
    return Job.objects.filter(status=Job.Status.RUNNING).update(status=Job.Status.PENDING, started_at=None)


HEARTBEAT = settings.BASE_DIR / '.worker_heartbeat'
SCHEDULE_EVERY = 30  # seconds between checks for posts due to be published
LOCK = settings.BASE_DIR / '.run_worker.lock'


def beat():
    HEARTBEAT.touch()


def worker_alive(max_age=45):
    try:
        return time.time() - os.path.getmtime(HEARTBEAT) < max_age
    except OSError:
        return False


def acquire_lock():
    """Returns the open lock file, or None if another worker holds it."""
    lock = open(LOCK, 'w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        return None
    return lock


def _heartbeat_loop():
    while True:
        beat()
        time.sleep(10)


def work_forever(log=logger.info, once=False):
    # A separate beat keeps the worker 'alive' while one job runs for minutes.
    threading.Thread(target=_heartbeat_loop, name='wakeel-heartbeat', daemon=True).start()
    if recovered := recover_stale():
        log(f'Re-queued {recovered} interrupted job(s).')
    log('Worker started.')
    next_schedule_check = 0
    while True:
        beat()
        close_old_connections()
        if time.monotonic() >= next_schedule_check:
            next_schedule_check = time.monotonic() + SCHEDULE_EVERY
            try:
                if queued := social.enqueue_due():
                    log(f'Queued {queued} scheduled post(s) for publishing.')
            except Exception:  # never let scheduling take the worker down
                logger.exception('Could not queue scheduled posts')
        job = claim_next()
        if job is None:
            if once:
                return
            time.sleep(settings.WORKER_POLL_SECONDS)
            continue
        log(f'Running {job}…')
        job = run_job(job)
        log(f'  -> {job.status} {job.error or job.message}')
