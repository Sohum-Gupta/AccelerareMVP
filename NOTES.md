# NOTES

Things learned the hard way. Add an entry whenever something non-obvious comes up.

- 2026-10-07: `uv init` creates a packaged `src/` layout with a `[build-system]`; removed it because a Django site is an app, not a library.
- 2026-10-07: Django 6.1 configures email with `MAILERS = {"default": {...}}`, not `EMAIL_BACKEND`.
- 2026-10-07: `manage.py check --deploy` (not plain `check`) fails with `mail.E001` if production settings inherit the console mailer. The SMTP `MAILERS` override in `production.py` is deferred until a server mailbox exists; expect the deploy check to stay red until then.
- 2026-10-07: `local.py` must call `environ.Env.read_env(...)` *before* `from .base import *`, because `base.py` reads `SECRET_KEY` at import time.
- 2026-10-07: Docker Compose reads `.env` for its own `${VAR}` substitution. A Django secret key containing `$` triggers "variable is not set" warnings on every `docker compose up`. Generate keys without `$` (or escape as `$$`).
- 2026-10-07: ruff's default rules flag Django idioms (class-level lists in models, generated migrations). `pyproject.toml` excludes `apps/*/migrations` and ignores RUF012 rather than littering models with `# noqa`.
- 2026-10-07: WhiteNoise's `CompressedManifestStaticFilesStorage` needs `collectstatic` to have run or every `{% static %}` raises when `DEBUG` is off (tests run with DEBUG off). `local.py` swaps in plain `StaticFilesStorage` with `WHITENOISE_USE_FINDERS`; production keeps the manifest storage and the Dockerfile runs `collectstatic`.
- 2026-10-07: `manage.py` defaults to local settings, so inside the container `python manage.py migrate` or `check --deploy` would run with DEBUG on. The Dockerfile sets `DJANGO_SETTINGS_MODULE=config.settings.production` so the image is always production; laptop runs are unaffected.
- 2026-10-07: gunicorn 26 opens a control socket under the user's home directory. The non-root container user has no home, which logged a permission error; the Dockerfile CMD passes `--no-control-socket` since we do not use it.
- 2026-10-07: testing the image locally behind production settings needs `X-Forwarded-Proto: https` on the request (as Caddy sends it), otherwise `SECURE_SSL_REDIRECT` answers 301. Example: `curl -H 'X-Forwarded-Proto: https' http://localhost:8001/health`.
- 2026-10-07: Production email is required config. `production.py` reads `EMAIL_HOST`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` and `DEFAULT_FROM_EMAIL` with no defaults, so a missing one stops startup. Anything that loads production settings (the Dockerfile's `collectstatic`, tests) must supply throwaway values. Real delivery is untested until the server exists.
- 2026-10-07: A reusable workflow (`workflow_call`) must not share a `concurrency` group with its caller, or GitHub cancels it. `ci.yml` uses `ci-<event>-<ref>` and `deploy.yml` uses `deploy-<ref>`.
- 2026-10-07: `manage.py check --deploy` exits 0 when it only finds warnings. The smoke test passes `--fail-level WARNING` so a new security warning fails the run.
- 2026-10-07: The image is built for `linux/arm64` on an x86 runner through QEMU emulation (about two minutes). The smoke test boots the emulated ARM image, so an architecture-specific failure shows up in CI and not on the server.
- 2026-10-07: The ghcr.io package inherited the public repo's visibility; an anonymous `docker pull` works. If the repo is ever made private, the server will need `docker login ghcr.io` with a token that has `read:packages`.

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
| Domain `theaccelerare.com` | registered at GoDaddy (DNS also at GoDaddy); live Wix site on `@` and `www`; Microsoft 365 mail via MX | GoDaddy DNS panel | add one A record for the platform subdomain (working name `app.theaccelerare.com`) pointing at the Elastic IP; do not touch `@`, `www` or MX records. Set `ALLOWED_HOSTS` and the Caddyfile to the same name |
| `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `DEFAULT_FROM_EMAIL` | the sending mailbox (personal for now, Amazon SES later) | server env in production (AWS Parameter Store) | create an app-specific password for the mailbox, store the five values; port defaults to 587 |
| Container image `ghcr.io/<owner>/<repo>` | GitHub (the repo's owner) | built by `deploy.yml` on every push to `main`; name derived from `github.repository` | nothing to edit. After moving the repo, the first push to `main` publishes under the new owner. Check the package's visibility, and update the server's compose file to the new image name |
| `GITHUB_TOKEN` (push to ghcr.io) | GitHub, created per run | automatic; `packages: write` on the image job only | nothing to do, no personal access token is stored anywhere |
