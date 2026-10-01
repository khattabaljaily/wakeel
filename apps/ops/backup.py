"""Daily backups of the database and uploaded files, careful with disk space.

- Database: a compressed dump per run (mysqldump --single-transaction | gzip; SQLite is copied).
- Media: an rsync snapshot per run, hard-linked to the previous one (--link-dest), so a file
  that didn't change costs no extra space; only new or changed files take room.
- Retention: the last BACKUP_KEEP_DAILY runs, plus one per week for BACKUP_KEEP_WEEKLY weeks.
- Guards: if the backups grow past BACKUP_MAX_GB, or the disk's free space would drop below
  BACKUP_MIN_FREE_GB, the oldest backups go first; if there is still no room the run is skipped.

The outcome is written to status.json in the backup folder; the console's system page reads it,
and system admins are emailed when a run fails.
"""
import datetime
import gzip
import json
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

logger = logging.getLogger(__name__)

STAMP = '%Y%m%d-%H%M'
GB = 1024 ** 3


def backup_dir():
    return Path(settings.BACKUP_DIR)


def _dir_size(path):
    """Real disk use: hard-linked files are counted once."""
    seen, total = set(), 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                st = os.lstat(os.path.join(root, name))
            except OSError:
                continue
            if st.st_ino not in seen:
                seen.add(st.st_ino)
                total += st.st_blocks * 512
    return total


def _runs(kind):
    """Existing backups of one kind, oldest first: [(datetime, path)]."""
    folder = backup_dir() / kind
    runs = []
    for path in folder.glob('*') if folder.exists() else []:
        try:
            when = datetime.datetime.strptime(path.name.split('.')[0], STAMP)
        except ValueError:
            continue
        runs.append((when, path))
    return sorted(runs)


def _remove(path):
    shutil.rmtree(path) if path.is_dir() else path.unlink(missing_ok=True)


def _keep(runs, daily, weekly):
    """Paths to keep: the newest `daily` runs, plus the newest run of each of the last `weekly` weeks."""
    keep = {p for _, p in runs[-daily:]} if daily else set()
    weeks = {}
    for when, path in runs:
        weeks[when.isocalendar()[:2]] = path  # later runs overwrite: newest of each week
    for week in sorted(weeks)[-weekly:] if weekly else []:
        keep.add(weeks[week])
    return keep


def prune():
    for kind in ('db', 'media'):
        runs = _runs(kind)
        keep = _keep(runs, settings.BACKUP_KEEP_DAILY, settings.BACKUP_KEEP_WEEKLY)
        for _when, path in runs:
            if path not in keep:
                _remove(path)


def _make_room(needed):
    """Delete the oldest backups until the size cap and the free-space floor both hold. Never deletes the newest."""
    cap, floor = settings.BACKUP_MAX_GB * GB, settings.BACKUP_MIN_FREE_GB * GB
    while True:
        free = shutil.disk_usage(backup_dir()).free
        used = _dir_size(backup_dir())
        if used + needed <= cap and free - needed >= floor:
            return True
        oldest = sorted(r for kind in ('db', 'media') for r in _runs(kind)[:-1])
        if not oldest:
            return False
        _remove(oldest[0][1])


def _dump_database(target):
    db = settings.DATABASES['default']
    if db['ENGINE'].endswith('sqlite3'):
        with open(db['NAME'], 'rb') as src, gzip.open(target, 'wb') as out:
            shutil.copyfileobj(src, out)
        return
    # Credentials go through a private option file, never the command line.
    with tempfile.NamedTemporaryFile('w', suffix='.cnf', delete=False) as cnf:
        cnf.write(f"[client]\nuser={db['USER']}\npassword=\"{db['PASSWORD']}\"\nhost={db.get('HOST') or 'localhost'}\n")
        if db.get('PORT'):
            cnf.write(f"port={db['PORT']}\n")
    os.chmod(cnf.name, 0o600)
    try:
        with gzip.open(target, 'wb') as out:
            proc = subprocess.Popen(
                ['mysqldump', f'--defaults-extra-file={cnf.name}', '--single-transaction', '--quick',
                 '--routines', '--no-tablespaces', '--default-character-set=utf8mb4', db['NAME']],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            shutil.copyfileobj(proc.stdout, out)
            _out, err = proc.communicate()
        if proc.returncode:
            raise RuntimeError(f'mysqldump failed: {err.decode(errors="replace")[:500]}')
    finally:
        os.unlink(cnf.name)


def _snapshot_media(target):
    previous = [p for _, p in _runs('media')]
    cmd = ['rsync', '-a', '--delete', '--exclude', 'tmp/']
    if previous:
        cmd.append(f'--link-dest={previous[-1]}')
    cmd += [f'{settings.MEDIA_ROOT}/', f'{target}/']
    subprocess.run(cmd, check=True, capture_output=True)


def run():
    """One backup run. Returns the status dict (also saved to status.json)."""
    root = backup_dir()
    for kind in ('db', 'media'):
        (root / kind).mkdir(parents=True, exist_ok=True)
    os.chmod(root, 0o700)  # dumps hold password hashes and tokens: owner only
    stamp = timezone.localtime().strftime(STAMP)
    status = {'started_at': timezone.now().isoformat(), 'ok': False, 'error': ''}
    try:
        prune()
        # Room for a new DB dump plus whatever changed in media (bounded by the media size).
        media_size = _dir_size(settings.MEDIA_ROOT) if Path(settings.MEDIA_ROOT).exists() else 0
        if not _make_room(needed=media_size + 50 * 1024 ** 2):
            raise RuntimeError('No room for a backup: raise BACKUP_MAX_GB or free disk space.')
        db_file = root / 'db' / f'{stamp}.sql.gz'
        _dump_database(db_file)
        media_dir = root / 'media' / stamp
        if Path(settings.MEDIA_ROOT).exists():
            _snapshot_media(media_dir)
        prune()
        status.update(ok=True, db_file=db_file.name, db_bytes=db_file.stat().st_size)
    except Exception as exc:
        logger.exception('Backup failed')
        status['error'] = str(exc)
        try:
            _email_superusers(_('فشل النسخ الاحتياطي لوكيل'), status['error'])
        except Exception:
            logger.exception('Could not email the backup failure')
    status.update(
        finished_at=timezone.now().isoformat(),
        total_bytes=_dir_size(root),
        free_bytes=shutil.disk_usage(root).free,
        db_runs=len(_runs('db')),
        media_runs=len(_runs('media')),
    )
    (root / 'status.json').write_text(json.dumps(status, ensure_ascii=False, indent=2))
    return status


def _email_superusers(subject, body):
    from apps.accounts.models import User
    to = list(User.objects.filter(is_superuser=True, is_active=True).exclude(email='').values_list('email', flat=True))
    if to:
        send_mail(subject, body, None, to)


def last_status():
    try:
        status = json.loads((backup_dir() / 'status.json').read_text())
    except (OSError, ValueError):
        return None
    status['finished_at'] = datetime.datetime.fromisoformat(status['finished_at']) if status.get('finished_at') else None
    return status
