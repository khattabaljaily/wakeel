#!/usr/bin/env bash
# Deploy the pushed `main` branch to production (https://wakeelservice.com).
# Usage: ./deploy.sh   (run from your PC after the commit is pushed to GitHub)
#
# The server's Python environment was built with uv (it has no pip), so packages are installed with `uv pip`.
# Whether the commit was pushed is checked on the server (it fetches main and compares), not with the local
# origin/main, which does not move when the push goes through another ssh alias.
set -euo pipefail

HOST=Server
APP_DIR=/home/enjaz/projects/wakeel
UV=/home/.khattab/.local/bin/uv

if [ -n "$(git status --porcelain)" ]; then
    echo "Commit your changes first." >&2
    exit 1
fi
LOCAL=$(git rev-parse HEAD)

ssh "$HOST" bash -s <<REMOTE
set -euo pipefail
cd $APP_DIR
git fetch -q origin main
if [ "\$(git rev-parse FETCH_HEAD)" != "$LOCAL" ]; then
    echo "Push the commit to GitHub first: GitHub has \$(git rev-parse --short FETCH_HEAD), you are deploying ${LOCAL:0:7}." >&2
    exit 1
fi
git pull --ff-only origin main
$UV pip install -q -r requirements.txt --python .env/bin/python
.env/bin/playwright install chromium > /dev/null
.env/bin/python manage.py migrate --noinput
.env/bin/python manage.py collectstatic --noinput | tail -1
.env/bin/python manage.py check --deploy --fail-level ERROR
sudo systemctl restart wakeel wakeel-worker
sleep 3
systemctl is-active wakeel wakeel-worker
curl -s -o /dev/null -w "Site: %{http_code}\n" https://wakeelservice.com/accounts/login/
git log --oneline -1
REMOTE
