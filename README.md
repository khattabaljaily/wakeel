# Wakeel (وكيل)

An AI marketing manager for companies, built to replace a marketing agency. It learns a company's brand, writes a monthly social media strategy, writes every post, designs the post images in the brand's colours, fonts and logo, and lays everything out in a calendar for review and approval.

It is multi-tenant SaaS: one account can run several companies (the pilots are Enjaz in Sudan and Banan in Qatar), and each company has its own team, roles, brand kit, media library, plans and posts.

---

## Tech Stack

| | |
|---|---|
| **Backend** | Django 5.2, Python 3.12, Django REST Framework (session auth, used by the app's own AJAX) |
| **Database** | MySQL in production, SQLite for local development |
| **Frontend** | Django templates, Bootstrap 5 RTL, Bootstrap Icons, vanilla JS (AJAX) |
| **AI** | Claude (Anthropic API, structured outputs) or DeepSeek (OpenAI-compatible JSON mode), chosen by `AI_PROVIDER` |
| **Design** | HTML/CSS post templates rendered to PNG by headless Chrome (Playwright) |
| **Fonts** | Arabic Google Fonts served locally from `static/fonts/` |

---

## How it works

1. **Brand kit**: during onboarding, the company describes its business, audience, tone of voice, do's and don'ts, colours, fonts, logo and contact channels.
2. **Content plan**: pick a month, the platforms (Facebook, Instagram, TikTok), how many posts per week, and an optional brief. A background job asks the AI for the month's strategy (goals, content pillars, key dates) and every post: idea, caption, hashtags, posting time, design text, template choice, and a shooting script for reels/TikTok.
3. **Design**: a second job renders each post image from one of seven templates (`bold`, `gradient`, `photo`, `split`, `minimal`, `quote`, `offer`) in square, 4:5 or 9:16 sizes. Photos from the company's media library can be used as backgrounds.
4. **Review**: posts start as *awaiting review*. The post editor has a live preview (plus an Instagram/Facebook feed mock), template/size/background pickers, one-click AI rewrites, a comment thread, and a status workflow: draft → review → approved → published. Editors prepare posts; owners/admins approve them. The calendar supports drag and drop to reschedule and shows local occasions.
5. **Client approval**: a manager can share a plan through a secret link (`/review/<token>/`). The client approves posts, requests changes or comments without an account; internal comments stay hidden.
6. **Publish**: connect a Facebook Page and its Instagram professional account (Company → حسابات النشر), then publish an approved post with one click, or turn on auto-publishing so the worker publishes approved posts at their time. Reels and TikTok stay manual (download the image / copy the caption / export a plan's captions).

### Occasions

`apps/content/occasions.py` lists the occasions that matter to the company's country (from its country field, else its timezone): national days, shopping days, and Islamic occasions computed with the Umm al-Qura calendar (`hijridate`). They are passed to the planner as trusted dates and shown on the calendar.

### Notifications

In-app notifications (bell in the top bar) for: posts sent for review (managers), approvals and change requests (authors), comments, client feedback, plans ready or failed, and publishing results. Change requests, client feedback, plan results and publishing failures are also emailed; each user can turn email off in account settings.

### Background jobs

Slow work (AI calls, image rendering, publishing) runs in `manage.py run_worker` (or inside `runserver` in development), a single worker that polls the `Job` table. Pages that start a job poll `/api/jobs/<id>/` for progress, warn when no worker is alive (heartbeat file), and can cancel a job; a job cancelled mid-run has its result discarded. Every 30 seconds the worker also queues approved posts that are due, for companies with auto-publishing on (each post is tried once automatically; posts more than 6 hours late are left for a person). Token usage is recorded per job and shown to managers on the AI usage page.

### Roles

| Role | Can |
|---|---|
| Owner / Admin | Everything, including approving and publishing posts, brand kit, team, client links, publishing accounts, AI usage |
| Editor | Create plans, edit posts, send them for review, comment |
| Viewer | Read and comment |

---

## Quick Start

```bash
python3 -m venv .env
source .env/bin/activate
pip install -r requirements.txt

cp secrets.example.json secrets.json   # then edit it (see below)
python manage.py migrate
python manage.py createsuperuser        # optional, for /admin/

python manage.py runserver
```

In development (`DEBUG: true`), `runserver` also runs the background worker in a thread, so one terminal is enough. In production run `manage.py run_worker` as its own service; a lock file keeps a single worker active either way.

Open http://127.0.0.1:8000/, create an account, and follow the onboarding.

### secrets.json

| Key | Purpose |
|---|---|
| `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` | Standard Django settings |
| `DATABASE` | Django database dict (MySQL in production; `{"ENGINE": "django.db.backends.sqlite3", "NAME": "db.sqlite3"}` locally) |
| `AI_PROVIDER` | `anthropic` (Claude) or `deepseek` |
| `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` | Claude key and model (default `claude-opus-5`) |
| `DEEPSEEK_API_KEY`, `DEEPSEEK_MODEL` | DeepSeek key and model (default `deepseek-v4-pro`; `deepseek-flash` is cheaper) |
| `DEEPSEEK_OFF_PEAK_UTC` | DeepSeek's off-peak window in UTC, `["16:30", "00:30"]` by default. DeepSeek prices (per model, cache hit/miss, peak/off-peak) are built into `apps/ai/pricing.py`, and each job's cost is stored when it runs |
| `AI_PRICE_INPUT_PER_MTOK`, `AI_PRICE_OUTPUT_PER_MTOK` | Flat USD price per million tokens for other models (Claude); without it their jobs show no cost |
| `SITE_URL` | Public address of the site, used in email links and for images Instagram downloads (must be public for Instagram publishing) |
| `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`, `DEFAULT_FROM_EMAIL` | SMTP for password reset and notifications. Empty `EMAIL_HOST` prints emails to the console |
| `META_APP_ID`, `META_APP_SECRET`, `META_GRAPH_VERSION` | Meta app for Facebook/Instagram publishing. Add `SITE_URL/company/social/meta/callback/` as a valid OAuth redirect URI. Publishing to accounts other than the app's testers needs Meta app review for `pages_manage_posts` and `instagram_content_publish` |
| `CHROME_PATH` | Path to Chrome/Chromium for rendering. Empty = Playwright's bundled Chromium (`playwright install chromium`) |
| `ALLOW_REGISTRATION` | Open sign-up (default `true`) |

Without a key for the selected provider the app runs but cannot generate plans or rewrite posts.
With DeepSeek, the JSON shape is described in the prompt rather than enforced by the API, so replies are validated and every field is sanitised before it is saved.

### Tests

```bash
python manage.py test apps
```

---

## Project layout

```
apps/
  accounts/    custom user, email login, registration
  companies/   tenants (Company), memberships & roles, media library, current-company middleware
  content/     content plans, posts, calendar, post editor, plan -> posts services
  ai/          AI client (Claude / DeepSeek) and the planning / rewriting prompts and JSON schemas
  studio/      design templates (templates/studio/designs/) and the Chrome renderer
  jobs/        background job model and the run_worker command
  api/         JSON endpoints used by the front-end (status, reschedule, rewrite, render, comments, publish, job polling)
  notifications/  in-app + email notifications
  social/      Meta connection (Facebook Page + Instagram) and publishing
templates/     pages (RTL Arabic UI)
static/        css, js, fonts, logo
```

## Roadmap

- **Next**: TikTok publishing (Content Posting API, needs the shot video), pull post insights from Meta.
- **Later**: learn from performance to improve next month's plan, suggested replies to comments, subscriptions and billing for the SaaS.
