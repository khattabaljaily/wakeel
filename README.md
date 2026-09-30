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
4. **Review**: posts start as *awaiting review*. The post editor has a live preview, template/size/background pickers, one-click AI rewrites, and a status workflow: draft → review → approved → published. Editors prepare posts; owners/admins approve them. The calendar supports drag and drop to reschedule.
5. **Publish** (for now): download the image and copy the caption, or export all captions of a plan as text. Direct publishing through the Meta and TikTok APIs is the next phase.

### Background jobs

Slow work (AI calls, image rendering) runs in `manage.py run_worker` (or inside `runserver` in development), a single worker that polls the `Job` table. Pages that start a job poll `/api/jobs/<id>/` for progress, warn when no worker is alive (heartbeat file), and can cancel a job; a job cancelled mid-run has its result discarded. Token usage is recorded per job so AI cost per company can be priced later.

### Roles

| Role | Can |
|---|---|
| Owner / Admin | Everything, including approving posts, brand kit, team |
| Editor | Create plans, edit posts, send them for review |
| Viewer | Read only |

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

Without a key for the selected provider the app runs but cannot generate plans or rewrite posts.
With DeepSeek, the JSON shape is described in the prompt rather than enforced by the API, so replies are validated and every field is sanitised before it is saved.
| `CHROME_PATH` | Path to Chrome/Chromium for rendering. Empty = Playwright's bundled Chromium (`playwright install chromium`) |
| `ALLOW_REGISTRATION` | Open sign-up (default `true`) |

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
  api/         JSON endpoints used by the front-end (status, reschedule, rewrite, render, job polling)
templates/     pages (RTL Arabic UI)
static/        css, js, fonts, logo
```

## Roadmap

- **Phase 2**: connect Facebook/Instagram (Meta Graph API) and TikTok, publish on schedule, pull post insights.
- **Phase 3**: learn from performance to improve next month's plan, suggested replies to comments, subscriptions and billing for the SaaS.
