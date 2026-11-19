# Deploying Wakeel

Nothing here is run automatically. Deploy, SSH to production and service restarts happen only when the owner asks, and every
production command is shown to the owner first. Production: `Server`, `/home/enjaz/projects/wakeel`, services `wakeel` and
`wakeel-worker`, gunicorn on 127.0.0.1:8109, nginx, MySQL `wakeel`.

## Before the first deploy of the merged product

1. **Backup** the database and `secrets.json`.
2. **Secrets** (only in the server's `secrets.json`, never in `settings.py`):
   - `FILE_ENCRYPTION_KEY`: required, production refuses to start without it. Create it with `manage.py make_file_key` and keep a copy **outside** the server (without it, private files cannot be read).
   - `ANTHROPIC_API_KEY` (Claude is not tried in production yet: try it on a test company first) and `DEEPSEEK_API_KEY`.
   - `AI_MONTHLY_BUDGET_USD` (default 100), optional `FORM_MAX_RESPONSES` (default 1000), `ASSISTANT_DAILY_MESSAGES` (default 60).
   - Mail: `EMAIL_*`, `DEFAULT_FROM_EMAIL`, `SUPPORT_EMAIL` (Enjaz addresses).
   - Payments per operator: `GATEWAYS` / `PAYMENT_LINKS` keyed by the operator (`jovia`), and the Stripe webhook at `SITE_URL/billing/webhook/<operator>/` (events `checkout.session.completed`).
   - `VAPID_*` for browser notifications, `CHROME_BIN` (or `google-chrome` on PATH) for PDFs, `WHATSAPP_*` if used.
   - Optional `LEGAL_ENTITY` / `LEGAL_ENTITY_AR` to override the operator named on the public pages.
3. **Packages**: `pip install -r requirements.txt`. `enjaz-operators` (v0.1.1) and `enjaz-docai` come from GitHub over SSH, so the server needs a deploy key.
4. **Chrome** on the server for PDF and Word-to-PDF rendering.
5. **Outbound ports** for the mailbox: 993/143 (IMAP) and 465/587/25/2525 (SMTP).
6. **Migrations**: many (companies, jobs, notifications, accounts, credits, billing 0001-0002, audit, identity, library, documents, docops, sharing, brand, presentations, forms, tasks, notes, contacts, announcements, mail). Run `manage.py migrate`.
7. **Crons**:
   - `manage.py send_expiry_reminders` daily
   - `manage.py send_note_reminders` every few minutes
   - `manage.py prune_assistant` monthly (optional)
   - the existing backup job
8. **Existing companies** have a zero balance, so their paid services stop: exempt or fund them from `/ops/subscriptions/<id>/` before opening.
9. Production companies are assigned the operator `jovia` by default (set the operator in `/ops/subscriptions/<id>/` if a company should differ).

## Every deploy

`./deploy.sh` pulls `origin/main`, installs requirements, migrates, collects static files, runs `check --deploy`, restarts both
services and checks the login page. Run it only after the owner asks.

## After the deploy

- Open `/ops/system/`: AI keys, worker, mail and backup should be green.
- Log in as a test company: wallet shown, one paid service with the price shown equal to the price charged.
- Check the legal pages and the footer ("Developed by Enjaz, managed and operated by JOVIA SAT").
