# Moving Wakeel on the server to `/home/enjaz/projects/wakeel`

**A plan only. Nothing here has been run.** Each step is shown to the owner first and runs only after the owner says yes.
Target: the production server `Server`. Today: `/home/banan/projects/wakeel` (services `wakeel`, `wakeel-worker`, nginx site
`wakeel`, MySQL `wakeel`). After: the same app in `/home/enjaz/projects/wakeel`, next to the other Enjaz projects.
Expected downtime: a few minutes (the services are stopped while the folder is copied and restarted from the new place).

## Phase 0: read-only inspection (no changes)

These tell us what the move really touches. Output only; nothing is edited.

1. `id; ls -ld /home/enjaz /home/enjaz/projects /home/banan/projects/wakeel; ls /home/enjaz/projects` (does the target exist, who owns it, what the other Enjaz projects look like).
2. `systemctl cat wakeel wakeel-worker` (the user, `WorkingDirectory`, `ExecStart`, `EnvironmentFile`).
3. `cat /etc/nginx/sites-enabled/wakeel` (the `static` / `media` aliases and the proxy port 8109).
4. `crontab -l` for the users involved, and `ls /etc/cron.d` (reminder jobs and the backup job, whose paths must change).
5. `du -sh /home/banan/projects/wakeel` and its `media/`, `private/`, `logs/` (size to copy), plus `df -h /home` (room for a second copy).
6. `ls -l /home/banan/projects/wakeel/secrets.json` (permissions to keep).
7. Which Linux user the other Enjaz projects' services run as (`systemctl cat <one of them>`), so Wakeel follows the same convention.

## Phase 1: backups (before touching anything)

1. Dump the database: `mysqldump --single-transaction wakeel > /home/enjaz/backups/wakeel-<date>.sql` (or wherever the existing backup job writes), and check the file is not empty.
2. Copy `secrets.json` and the `private/` folder (the encrypted files) to a safe place. **Keep a copy of `FILE_ENCRYPTION_KEY` outside the server**: without it the private files cannot be read, wherever they live.
3. Note the current commit: `git -C /home/banan/projects/wakeel log --oneline -1` (the rollback point).

## Phase 2: prepare the new place while the site is still up

1. Create `/home/enjaz/projects/wakeel` with the right owner (the user the service will run as).
2. Copy the project: `rsync -a --exclude .env /home/banan/projects/wakeel/ /home/enjaz/projects/wakeel/` (the virtualenv `.env` is **not** copied: a virtualenv remembers its path and breaks when moved).
3. Create a new virtualenv there and install: `python3 -m venv .env && .env/bin/pip install -r requirements.txt` (needs the server's GitHub SSH key for `enjaz-operators` v0.1.1 and `enjaz-docai`), then `.env/bin/playwright install chromium` if the server renders with Playwright.
4. Check without switching: `.env/bin/python manage.py check --deploy` against the same database.

## Phase 3: the switch (the short downtime)

1. `sudo systemctl stop wakeel wakeel-worker`.
2. A last `rsync` of `media/`, `private/`, `logs/` and `secrets.json` to catch anything written since Phase 2.
3. Edit the two unit files (`WorkingDirectory`, `ExecStart`, and `User` / `Group` if the user changes), then `sudo systemctl daemon-reload`.
4. Edit the nginx site: the `alias` paths for static and media; `sudo nginx -t`; `sudo systemctl reload nginx`.
5. `.env/bin/python manage.py migrate --noinput` (already up to date; confirms the database connection) and `collectstatic --noinput`.
6. `sudo systemctl start wakeel wakeel-worker`; check `systemctl is-active wakeel wakeel-worker`.
7. Update the cron lines (`send_expiry_reminders`, `send_note_reminders`, the backup job) to the new path.

## Phase 4: verify

1. The login page returns 200 at https://wakeelservice.com/accounts/login/.
2. Sign in as a test company: open a library paper (a private file must open: proves the key and the files moved well), view the wallet, and run one cheap paid service (the shown price must equal the charge).
3. `/ops/system/`: worker, AI keys, mail and backup are green.
4. The worker log (`logs/worker.log`) has no errors after a few minutes.

## Rollback (if anything above fails)

The old folder stays untouched until the owner confirms everything works: point the unit files and nginx back to
`/home/banan/projects/wakeel`, `daemon-reload`, `nginx -t`, reload, start the services. The database was not changed by the move.

## After a week of good running

With the owner's approval only: remove `/home/banan/projects/wakeel`. Then `deploy.sh` (already pointing to the new path) is the
only way to update the server.
