# Tech Stack — Survey Platform

As of 2026-10-05 · Planning Session 3 · Depends on `01-requirements.md` (v2) and `02-architecture.md`

## Summary

Python 3.12 and Django, server-rendered templates with HTMX and Tailwind, PostgreSQL through the Django ORM, a small database-backed job worker, and `django-allauth` for email verification and later SSO. Everything is pinned in a lockfile and runs the same way on a Mac and on a Linux server.

The guiding rule: choose the boring, well-documented option, and use Django's built-in piece whenever one exists.

## The stack

| Layer | Choice | Role in this project |
| --- | --- | --- |
| Language | Python 3.12 | Everything: web app, worker, scripts, tests |
| Web framework | Django (latest LTS at project start) | Routing, views, templates, ORM, migrations, forms, sessions, CSRF, built-in admin, email sending, management commands |
| Auth core | `django.contrib.auth` with a custom user model | Login, logout, password hashing (argon2), password reset. Custom user model from day one so email is the username and the model can grow |
| Auth extras | `django-allauth` | Email verification, multiple emails per account, resend and expiry handling; social and SAML login in Phase 3 by config |
| Templates | Django templates | Every page; one base layout, one template per screen |
| Interactivity | HTMX | Per-answer autosave, inline table filtering, invite and code forms without full reloads. No JavaScript build step |
| Styling | Tailwind CSS via the standalone CLI | Matches the Wix design; the CLI produces one CSS file and needs no Node project |
| Database | PostgreSQL 16 | All data; JSONB for `response.answers`, `result.payload`, `match_candidate.signals`, `job.payload` |
| DB driver | `psycopg` (v3) | Django's PostgreSQL backend |
| Background jobs | Custom `job` table and a worker management command | Matching, outbound email, algorithm runs, large exports. No Celery, no Redis |
| Email | Django SMTP backend (personal mailbox) now; `django-ses` later | Verification, password reset, invites. Swapped by settings only |
| Configuration | `django-environ` reading environment variables | `.env` file locally; environment or secrets manager on AWS. Region, hosts, credentials all live here |
| Testing | `pytest`, `pytest-django`, `factory_boy` | Unit tests per module; tenant-isolation tests are mandatory before launch |
| Lint and format | `ruff` | One tool for both; run in pre-commit and CI |
| Dependencies | `uv` with `pyproject.toml` and `uv.lock` | Fast, reproducible installs on Mac and Linux |
| Containers | Docker Compose for local PostgreSQL; a Dockerfile for the app | Same database engine locally and in production; the Dockerfile is the deploy unit (see Infrastructure doc) |
| Source control | Git, GitHub | Main branch deploys; CI runs tests and ruff on every push |
| Error tracking | Sentry (free tier) | Captures exceptions from web and worker with the request context |
| CSV export | Python standard library `csv` | Streamed response; no file storage needed |

Versions are pinned in `uv.lock` at project start and upgraded deliberately, not automatically.

## Repository layout

One repository, one Django project, one Django app per architecture module.

```
survey-platform/
├── pyproject.toml          # dependencies and tool config (ruff, pytest)
├── uv.lock
├── .env.example            # every setting the app reads, with safe defaults
├── docker-compose.yml      # local PostgreSQL only
├── Dockerfile              # app image for deployment
├── manage.py
├── config/                 # Django project: settings, urls, wsgi
│   ├── settings/
│   │   ├── base.py
│   │   ├── local.py
│   │   └── production.py
│   └── urls.py
├── apps/
│   ├── accounts/           # Person, Account, ContactPoint; allauth integration
│   ├── enterprises/        # Enterprise, Membership, Invite, JoinCode, SeatPool
│   ├── survey/             # SurveyVersion, Question; v1 fixture
│   ├── responses/          # Response; autosave and submit views
│   ├── entitlements/       # Entitlement; seat pool enforcement
│   ├── matching/           # MatchCandidate; rules.py; merge and unmerge
│   ├── results/            # Result; compute_result interface; tier filter
│   ├── exports/            # CSV views per scope
│   ├── audit/              # AuditLog and a helper to write entries
│   └── jobs/               # Job model, enqueue(), worker command
├── templates/              # base.html and one folder per app
├── static/
│   └── css/                # Tailwind input and built output
└── tests/                  # mirrors apps/; tenant isolation tests live here
```

Each app exposes a small set of plain functions (for example `enterprises.services.join_with_code(account, code)`) that other apps call. Views are thin: validate input, call a service, render a template. Business rules never live in templates or views.

## How the architecture maps to code

**Custom user model.** `accounts.Account` extends Django's `AbstractBaseUser`. Email is the login identifier. This must be set before the first migration; changing it later is painful.

**Person and contact points.** `Person` is a separate model that `Account` points to. `ContactPoint` rows hold emails and phones. allauth manages its own `EmailAddress` table for verification; a signal copies each verified email into `ContactPoint` so matching reads one table.

**allauth usage.** allauth handles verification emails, tokens and the verify-link view. The project supplies its own signup, login, enterprise-join and invite-accept views and templates; they call allauth's helpers rather than using allauth's pages. allauth's own URLs are mounted only for the pieces used (verification, password reset).

**Autosave.** Each question is a small form. Answering it sends an HTMX request to `responses:save_answer`, which writes one key into `response.answers` and returns the next question fragment. Submit is a separate view that validates all 25 answers are present, sets `status=submitted`, and enqueues jobs.

**Tenant scoping.** `enterprises.scoping.for_admin(request)` returns the active admin membership or raises; every enterprise-scoped queryset is built from it (`Response.objects.filter(membership__enterprise=membership.enterprise)`). No view reads an enterprise id from the URL.

**Jobs.** `jobs.enqueue(kind, payload, run_after=None)` inserts a row. `python manage.py run_worker` loops: select the oldest runnable unlocked job with `SELECT ... FOR UPDATE SKIP LOCKED`, lock it, dispatch by `kind` to a registered function, mark done or schedule a retry with exponential backoff (max 5 attempts), record the error text. Handlers must be idempotent.

**Algorithm interface.** `results/algorithm.py` defines `compute_result(response: Response) -> ResultPayload | None` and `ALGORITHM_VERSION`. The MVP implementation returns `None` and stores nothing. Phase 2 replaces the body; nothing else changes.

**Root admin.** Django admin, registered for every model, with read-only fields on `Response` after submission. Merge/unmerge, match review and deletion are custom admin actions that write `audit_log` rows.

**Enterprise admin.** Custom views and templates under `/enterprise/<slug>/`; the slug is resolved and then discarded in favour of the membership from `for_admin()`.

**Survey definition.** `survey/fixtures/v1.json` holds the 25 questions and is loaded by a data migration. Questions are read from the database at runtime.

**Settings split.** `base.py` holds everything common; `local.py` turns on debug and the console email backend; `production.py` enforces HTTPS, secure cookies and real email. The environment selects which one loads.

## Local development

1. Install `uv`, Docker Desktop, and the Tailwind standalone CLI.
2. `git clone`, then `uv sync` to create the virtualenv and install dependencies.
3. `cp .env.example .env` and fill in a database URL pointing at the Compose PostgreSQL.
4. `docker compose up -d` starts PostgreSQL.
5. `uv run python manage.py migrate` creates the schema and loads survey v1.
6. `uv run python manage.py createsuperuser` creates the root admin.
7. `uv run python manage.py runserver` and, in a second terminal, `uv run python manage.py run_worker`.
8. `tailwindcss -i static/css/input.css -o static/css/app.css --watch` rebuilds CSS on change.

Tests: `uv run pytest`. Lint: `uv run ruff check . && uv run ruff format --check .`.

## Testing priorities

| Priority | What | Why |
| --- | --- | --- |
| 1 | Tenant isolation: two enterprises, each admin's list, detail and export return nothing from the other | The most damaging bug class; required before any real customer |
| 2 | Join flows: invite accept, code redeem, cap and expiry, revoked code, seat pool exhausted | Where money and access meet |
| 3 | Response lifecycle: autosave, resume, submit, immutability after submit | Core product |
| 4 | Matching rules: each rule fires only on verified data; unmerge restores state | Wrong merges leak data between people |
| 5 | Deletion: everything gone, audit row present | DPDP obligation |

## Conventions

- Services over fat views: every write goes through a function in `<app>/services.py`.
- Every admin action and every deletion writes an `audit_log` row in the same transaction.
- Migrations are committed with the code that needs them and never edited after merge.
- Settings are read once in `config/settings`; no `os.environ` calls elsewhere.
- No raw SQL unless the ORM cannot express it; when used, it lives in one place with a comment.
- Dates and times are stored in UTC; rendered in the viewer's timezone (Asia/Kolkata default).

## Django in brief, for a near-first-time user

- A *project* is the whole site; an *app* is one module. Apps hold models, views, templates and tests for one concern.
- *Models* are Python classes that become database tables; *migrations* are generated files that change the schema when models change.
- A *view* takes a request and returns a response; URLs map paths to views; *templates* render HTML from a view's data.
- *Management commands* are scripts run with `manage.py`; the job worker is one.
- The *admin* is a generated UI for editing any registered model; it is the root-admin interface here.
- The *ORM* lets you query the database in Python (`Response.objects.filter(status="submitted")`) and handles PostgreSQL for you.

## Decision log

| Date | Decision | Reason |
| --- | --- | --- |
| 2026-10-07 | Django 6.1 installed (current release, not 5.2 LTS); uses `MAILERS` setting instead of `EMAIL_BACKEND` | Already installed; 6.2 LTS lands April 2027 |
| 2026-10-05 | Django over FastAPI or Flask | Built-in auth, ORM, migrations, admin and email save weeks for one developer |
| 2026-10-05 | `django-allauth` for verification and later SSO; own views and templates on top | Mature edge-case handling and config-only SSO; revisit if it fights the join flows |
| 2026-10-05 | Custom user model with email login from the first migration | Changing it later is costly |
| 2026-10-05 | HTMX plus Django templates, no JavaScript framework | Autosave and inline updates without a frontend build |
| 2026-10-05 | Tailwind via standalone CLI | Matches the Wix design without a Node project |
| 2026-10-05 | Custom job table and worker, no Celery or Redis | Zero fixed cost; swappable |
| 2026-10-05 | `uv`, `ruff`, `pytest` | Fast, single-purpose, standard |
| 2026-10-05 | Docker Compose for local PostgreSQL only; app runs natively on the Mac | Same database engine as production; fast reload loop |
| 2026-10-05 | Sentry free tier from the first deploy | Errors must be visible without user reports |
