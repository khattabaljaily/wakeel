import os
import sys
import threading

from django.apps import AppConfig
from django.conf import settings


class JobsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.jobs'

    def ready(self):
        # Local development: `runserver` also runs the background worker, so
        # plans and designs work without a second terminal. The autoreloader
        # starts two processes; only the child (RUN_MAIN) serves requests.
        if not (settings.DEBUG and 'runserver' in sys.argv):
            return
        if os.environ.get('RUN_MAIN') != 'true' and '--noreload' not in sys.argv:
            return
        from .runner import acquire_lock, work_forever

        lock = acquire_lock()
        if lock is None:  # a separate run_worker is already running
            return
        thread = threading.Thread(target=work_forever, name='wakeel-worker', daemon=True)
        thread.lock = lock  # keep the lock open for the thread's lifetime
        thread.start()
