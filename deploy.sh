#!/usr/bin/env bash
# Deploy the pushed `main` branch to production (https://wakeel.sharedlink.cc).
# Usage: ./deploy.sh   (run from your PC after `git push`)
set -euo pipefail

HOST=Server
APP_DIR=/home/general/projects/wakeel

if [ -n "$(git status --porcelain)" ] || [ "$(git rev-parse HEAD)" != "$(git rev-parse origin/main 2>/dev/null)" ]; then
    echo "Commit and push your changes to origin/main first." >&2
    exit 1
fi

ssh "$HOST" bash -s <<REMOTE
set -euo pipefail
cd $APP_DIR
git pull --ff-only origin main
.env/bin/pip install -q -r requirements.txt
.env/bin/playwright install chromium > /dev/null
.env/bin/python manage.py migrate --noinput
.env/bin/python manage.py collectstatic --noinput | tail -1
.env/bin/python manage.py check --deploy --fail-level ERROR
sudo systemctl restart wakeel wakeel-worker
sleep 3
systemctl is-active wakeel wakeel-worker
curl -s -o /dev/null -w "Site: %{http_code}\n" https://wakeel.sharedlink.cc/accounts/login/
git log --oneline -1
REMOTE
