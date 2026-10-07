# NOTES

Things learned the hard way. Add an entry whenever something non-obvious comes up.

- 2026-10-07: `uv init` creates a packaged `src/` layout with a `[build-system]`; removed it because a Django site is an app, not a library.
- 2026-10-07: Django 6.1 configures email with `MAILERS = {"default": {...}}`, not `EMAIL_BACKEND`.
- 2026-10-07: `manage.py check --deploy` (not plain `check`) fails with `mail.E001` if production settings inherit the console mailer. The SMTP `MAILERS` override in `production.py` is deferred until a server mailbox exists; expect the deploy check to stay red until then.
- 2026-10-07: `local.py` must call `environ.Env.read_env(...)` *before* `from .base import *`, because `base.py` reads `SECRET_KEY` at import time.
- 2026-10-07: Docker Compose reads `.env` for its own `${VAR}` substitution. A Django secret key containing `$` triggers "variable is not set" warnings on every `docker compose up`. Generate keys without `$` (or escape as `$$`).

## Porting checklist

Everything account-specific lives outside the code. To move to new GitHub,
Docker or AWS accounts, recreate the items below; nothing in the repo changes.
Append a row whenever a new external dependency appears.

| Dependency | Belongs to | Where its value lives | Set it by |
| --- | --- | --- | --- |
| `SECRET_KEY` | nobody (random) | `.env` locally; server env in production | generate a fresh one per environment |
| `DATABASE_URL` | local Docker / future AWS DB | `.env` locally; server env in production | match the database you create |
| `ALLOWED_HOSTS` | your domain | `.env` locally; server env in production | set to the real hostname |
| `SENTRY_DSN` | Sentry project | server env | create a Sentry project, copy its DSN |
| `postgres:16` image | public Docker Hub, no account | `docker-compose.yml` | nothing to do |
