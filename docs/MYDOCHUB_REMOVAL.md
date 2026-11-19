# Removing MyDocHub (after the new Wakeel runs on wakeelservice.com)

**A plan only. Nothing here has been run, and nothing is deleted until the owner says so for each step, after the new Wakeel
has run well for the agreed time.** MyDocHub has no real users (owner's rule 6), so no data is migrated.

## Before anything is deleted

1. The new Wakeel is live on https://wakeelservice.com in `/home/enjaz/projects/wakeel`, a test company has topped up and used a paid service, and the owner confirmed.
2. **Keep what Wakeel needs from MyDocHub:** its AI keys (Anthropic, DeepSeek) are copied into Wakeel's production `secrets.json` first (the owner says from where), and the three Stripe payment links already live in Wakeel's secrets. `enjaz-docai` and `enjaz-operators` are shared packages: they stay.
3. **A last backup, kept outside the server for a month:** the MyDocHub database dump, its `secrets.json`, and its `media/` and `private/` folders.

## What there is on the server (inventory of 2026-11-19, read only)

- Services: `mydochub.service`, `mydochub-worker.service` (enabled).
- nginx site `mydochub` (mydochub.online, www.mydochub.online).
- Project folder `/home/enjaz/projects/mydochub` (602 MB), and its `~/logs/mydochub_*.log` files.
- Six cron lines in the `khattab` crontab: `send_note_reminders` (every minute), `send_expiry_reminders` (09:00), `prune_notifications`, `prune_trial_grants`, `prune_assistant`, and the pruning of `mydochub-*.sql` backups.
- Its backups in the shared backups folder (`mydochub-*.sql*`), its MySQL database and user (names to read from its settings), its gunicorn port.

## Deletion steps (each one confirmed by the owner)

1. Stop and disable the two services, remove the unit files, `daemon-reload`.
2. Remove the nginx site (`sites-enabled` link and `sites-available` file), `nginx -t`, reload.
3. Remove the six cron lines (keep the others: edit the crontab, do not replace it).
4. Drop the MySQL database and user (after the final backup is verified).
5. Delete `/home/enjaz/projects/mydochub`, its logs and old backups.
6. Domain `mydochub.online`: the DNS records and the Cloudflare zone are the owner's to remove or let expire.
7. GitHub: archive, then delete the `mydochub` repository (owner).
8. Locally: archive `/home/khattab/LocalServer/enjaz/projects/mydochub` (a tarball kept for a month), then delete it. Remove the references in the memory notes, and the ``../mydochub`` mentions in this repository's docs.
9. Stripe: nothing to remove: the payment links now belong to Wakeel. Rename or delete any MyDocHub-only Stripe objects (owner).

## The old Wakeel install (also after the switch)

- `/home/banan/projects/wakeel` (the old folder, kept untouched as the rollback until the owner confirms), its `.env`, and the six `secrets.json.bak-*` copies: moved out of the project and then deleted.
- The old address `wakeel.enjaztechnology.com`: the nginx site `wakeel`, its certificate and its entries in `ALLOWED_HOSTS` / `CSRF_TRUSTED_ORIGINS`; the DNS record is the owner's.
- `/home/banan/backups/wakeel` stays until the owner decides.
